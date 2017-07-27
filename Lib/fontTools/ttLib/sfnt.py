"""

	derived from ttLib/sfnt.py
	classes:

	SFNTReader
	SFNTWriter
	SFNTwoFFWriter

"""

import sys
import struct, sstruct
import numpy
import os
import zlib

class SFNTReader:
	
	def __init__(self, file, checkChecksums=1, fontNumber=-1):
		self.file = file
		self.checkChecksums = checkChecksums
		data = self.file.read(sfntDirectorySize)
		if len(data) <> sfntDirectorySize:
			from fontTools import ttLib
			raise ttLib.TTLibError, "Not a TrueType or OpenType font (not enough data)"
		sstruct.unpack(sfntDirectoryFormat, data, self)
		if self.sfntVersion == "ttcf":
			assert ttcHeaderSize == sfntDirectorySize
			sstruct.unpack(ttcHeaderFormat, data, self)
			assert self.Version == 0x00010000 or self.Version == 0x00020000, "unrecognized TTC version 0x%08x" % self.Version
			if not 0 <= fontNumber < self.numFonts:
				from fontTools import ttLib
				raise ttLib.TTLibError, "specify a font number between 0 and %d (inclusive)" % (self.numFonts - 1)
			offsetTable = struct.unpack(">%dL" % self.numFonts, self.file.read(self.numFonts * 4))
			if self.Version == 0x00020000:
				pass # ignoring version 2.0 signatures
			self.file.seek(offsetTable[fontNumber])
			data = self.file.read(sfntDirectorySize)
			sstruct.unpack(sfntDirectoryFormat, data, self)
		if self.sfntVersion not in ("\000\001\000\000", "OTTO", "true"):
			from fontTools import ttLib
			raise ttLib.TTLibError, "Not a TrueType or OpenType font (bad sfntVersion)"
		self.tables = {}
		for i in range(self.numTables):
			entry = SFNTDirectoryEntry()
			entry.fromFile(self.file)
			if entry.length > 0:
				self.tables[entry.tag] = entry
			else:
				# Ignore zero-length tables. This doesn't seem to be documented,
				# yet it's apparently how the Windows TT rasterizer behaves.
				# Besides, at least one font has been sighted which actually
				# *has* a zero-length table.
				pass
	
	def has_key(self, tag):
		return self.tables.has_key(tag)
	
	def keys(self):
		return self.tables.keys()
	
	def __getitem__(self, tag):
		"""Fetch the raw table data."""
		entry = self.tables[tag]
		self.file.seek(entry.offset)
		data = self.file.read(entry.length)
		if self.checkChecksums:
			if tag == 'head':
				# Beh: we have to special-case the 'head' table.
				checksum = calcChecksum(data[:8] + '\0\0\0\0' + data[12:])
			else:
				checksum = calcChecksum(data)
			if self.checkChecksums > 1:
				# Be obnoxious, and barf when it's wrong
				assert checksum == entry.checksum, "bad checksum for '%s' table" % tag
			elif checksum <> entry.checkSum:
				# Be friendly, and just print a warning.
				print "bad checksum for '%s' table" % tag
		return data
	
	def __delitem__(self, tag):
		del self.tables[tag]
	
	def close(self):
		self.file.close()

class SFNTWoFFWriter:

	def __init__(self, file, numTables, sfntVersion="\000\001\000\000"):
		self.file = file
		self.numTables = numTables
		self.sfntVersion = sfntVersion
		self.searchRange, self.entrySelector, self.rangeShift = getSearchRange(numTables)
		self.nextTableOffset = woffHeaderSize + (woffDirectoryEntrySize * numTables)
		print "self.nextTableOffset: '%s'" % self.nextTableOffset
		#self.nextTableOffset = sfntDirectorySize + numTables * sfntDirectoryEntrySize
		# clear out directory area
		self.file.seek(self.nextTableOffset)
		# make sure we're actually where we want to be. (XXX old cStringIO bug)
		#self.file.write('\0' * (self.nextTableOffset - self.file.tell()))
		self.tables = {}

	def __setitem__(self, tag, data):
		if self.tables.has_key(tag):
			entry = self.tables[tag]
			if len(data) <> entry.length:
				from fontTools import ttLib
				raise ttLib.TTLibError, "cannot rewrite '%s' table: length does not match directory entry" % tag
		else:
			entry = WOFFDirectoryEntry()
			entry.tag = tag
			entry.offset = self.nextTableOffset
			entry.origLength = len(data)
			# compress the data
			zdata = zlib.compress(data)
			entry.compLength = len(zdata)
		
			self.nextTableOffset = self.nextTableOffset + ((len(zdata) + 3) & ~3)

		self.file.seek(entry.offset)
		self.file.write(zdata)
		self.file.write('\0' * (self.nextTableOffset - self.file.tell()))
		assert self.nextTableOffset == self.file.tell()

		if tag == 'head':
			entry.origChecksum = calcChecksum(data[:8] + '\0\0\0\0' + data[12:])
		else:
			entry.origChecksum = calcChecksum(data)
		self.tables[tag] = entry

	def close(self):

		tableSizes = 0
		compTableSizes = 0

		for tag in self.tables:
			entry = self.tables[tag]
			tableSizes = tableSizes + entry.origLength
			compTableSizes = compTableSizes + entry.compLength

		# caclulate and write the header	
		woffHeaderObj = {} 
		woffHeaderObj['wOFFsignature'] = 'wOFF'
		woffHeaderObj['wOFFflavor'] = self.sfntVersion
		woffHeaderObj['wOFFlength'] = woffHeaderSize + (woffDirectoryEntrySize * self.numTables) + compTableSizes
		woffHeaderObj['wOFFnumTables'] = self.numTables
		woffHeaderObj['wOFFreserved'] = 0
		woffHeaderObj['wOFFtotalSfntSize'] = sfntDirectorySize + (sfntDirectoryEntrySize * self.numTables) + tableSizes
		woffHeaderObj['wOFFmajorVersion'] = 1
		woffHeaderObj['wOFFminorVersion'] = 0
		woffHeaderObj['wOFFmetaOffset'] = 0
		woffHeaderObj['wOFFmetaLength'] = 0
		woffHeaderObj['wOFFmetaOrigLength'] = 0
		woffHeaderObj['wOFFprivOffset'] = 0
		woffHeaderObj['wOFFprivLength'] = 0

		self.file.seek(0)
		self.file.write(sstruct.pack(woffHeaderFormat, woffHeaderObj))

		# write the woff directory

		for tag in self.tables:
			entry = self.tables[tag]
			directory = sstruct.pack(woffDirectoryEntryFormat, entry)
			self.file.write(directory)
	
class SFNTWriter:
	
	def __init__(self, file, numTables, sfntVersion="\000\001\000\000"):
		self.file = file
		self.numTables = numTables
		self.sfntVersion = sfntVersion
		self.searchRange, self.entrySelector, self.rangeShift = getSearchRange(numTables)
		self.nextTableOffset = sfntDirectorySize + numTables * sfntDirectoryEntrySize
		# clear out directory area
		self.file.seek(self.nextTableOffset)
		# make sure we're actually where we want to be. (XXX old cStringIO bug)
		self.file.write('\0' * (self.nextTableOffset - self.file.tell()))
		self.tables = {}
	
	def __setitem__(self, tag, data):
		"""Write raw table data to disk."""
		if self.tables.has_key(tag):
			# We've written this table to file before. If the length
			# of the data is still the same, we allow overwriting it.
			entry = self.tables[tag]
			if len(data) <> entry.length:
				from fontTools import ttLib
				raise ttLib.TTLibError, "cannot rewrite '%s' table: length does not match directory entry" % tag
		else:
			entry = SFNTDirectoryEntry()
			entry.tag = tag
			entry.offset = self.nextTableOffset
			entry.length = len(data)

		self.nextTableOffset = self.nextTableOffset + ((len(data) + 3) & ~3)
		self.file.seek(entry.offset)
		self.file.write(data)
		# Add NUL bytes to pad the table data to a 4-byte boundary.
		# Don't depend on f.seek() as we need to add the padding even if no
		# subsequent write follows (seek is lazy), ie. after the final table
		# in the font.
		self.file.write('\0' * (self.nextTableOffset - self.file.tell()))
		assert self.nextTableOffset == self.file.tell()
		
		if tag == 'head':
			entry.checkSum = calcChecksum(data[:8] + '\0\0\0\0' + data[12:])
		else:
			entry.checkSum = calcChecksum(data)
		self.tables[tag] = entry

	def close(self):
		"""All tables must have been written to disk. Now write the
		directory.
		"""
		tables = self.tables.items()
		tables.sort()
		if len(tables) <> self.numTables:
			from fontTools import ttLib
			raise ttLib.TTLibError, "wrong number of tables; expected %d, found %d" % (self.numTables, len(tables))
		
		directory = sstruct.pack(sfntDirectoryFormat, self)
		
		self.file.seek(sfntDirectorySize)
		seenHead = 0
		for tag, entry in tables:
			if tag == "head":
				seenHead = 1
			directory = directory + entry.toString()
		if seenHead:
			self.calcMasterChecksum(directory)
		self.file.seek(0)
		self.file.write(directory)
	
	def calcMasterChecksum(self, directory):
		# calculate checkSumAdjustment
		tags = self.tables.keys()
		checksums = numpy.zeros(len(tags)+1, numpy.uint32)
		for i in range(len(tags)):
			checksums[i] = self.tables[tags[i]].checkSum
		
		directory_end = sfntDirectorySize + len(self.tables) * sfntDirectoryEntrySize
		assert directory_end == len(directory)
		
		checksums[-1] = calcChecksum(directory)
		checksum = numpy.add.reduce(checksums,dtype=numpy.uint32)
		# BiboAfba!
		checksumadjustment = int(numpy.subtract.reduce(numpy.array([0xB1B0AFBA, checksum], numpy.uint32)))
		# write the checksum to the file
		self.file.seek(self.tables['head'].offset + 8)
		self.file.write(struct.pack(">L", checksumadjustment))


woffHeaderFormat = """ 
	> # big endian
	wOFFsignature:       4s # 0x774F4646 'wOFF'
	wOFFflavor:          4s  # The "sfnt version" 0x00010000 for TrueType or 0x4F54544F 'OTTO' for CFF
	wOFFlength:          I  # Total size of the WOFF file
	wOFFnumTables:       H  # Number of entries in directory of font tables.
	wOFFreserved:        H  # Reserved, must be set to zero.
	wOFFtotalSfntSize:   I  # Total size needed for the uncompressed font data
	wOFFmajorVersion:    H  # Major version of the WOFF font
	wOFFminorVersion:    H  # Minor version of the WOFF font
	wOFFmetaOffset:      I  # Offset to metadata block, from beginning of WOFF file
	wOFFmetaLength:      I  # Length of compressed metadata block
	wOFFmetaOrigLength:  I  # Uncompressed size of metadata block
	wOFFprivOffset:      I  # Offset to private data block
	wOFFprivLength:      I  # Length of private data block
"""
woffHeaderSize = sstruct.calcsize(woffHeaderFormat)

woffDirectoryEntryFormat = """ 
	> # big endian
	tag:          4s # 4-byte sfnt table identifier.
	offset:       I  # Offset to the data, from beginning of WOFF file.
	compLength:   I  # Length of the compressed data, excluding padding.
	origLength:   I  # Length of the uncompressed table, excluding padding.
	origChecksum: I  # Checksum of the uncompressed table.
"""
woffDirectoryEntrySize = sstruct.calcsize(woffDirectoryEntryFormat)

# -- sfnt directory helpers and cruft

ttcHeaderFormat = """
		> # big endian
		TTCTag:                  4s # "ttcf"
		Version:                 L  # 0x00010000 or 0x00020000
		numFonts:                L  # number of fonts
		# OffsetTable[numFonts]: L  # array with offsets from beginning of file
		# ulDsigTag:             L  # version 2.0 only
		# ulDsigLength:          L  # version 2.0 only
		# ulDsigOffset:          L  # version 2.0 only
"""

ttcHeaderSize = sstruct.calcsize(ttcHeaderFormat)

sfntDirectoryFormat = """
		> # big endian
		sfntVersion:    4s
		numTables:      H    # number of tables
		searchRange:    H    # (max2 <= numTables)*16
		entrySelector:  H    # log2(max2 <= numTables)
		rangeShift:     H    # numTables*16-searchRange
"""

sfntDirectorySize = sstruct.calcsize(sfntDirectoryFormat)

sfntDirectoryEntryFormat = """
		> # big endian
		tag:            4s
		checkSum:       L
		offset:         L
		length:         L
"""

sfntDirectoryEntrySize = sstruct.calcsize(sfntDirectoryEntryFormat)

class SFNTDirectoryEntry:
	
	def fromFile(self, file):
		sstruct.unpack(sfntDirectoryEntryFormat, 
				file.read(sfntDirectoryEntrySize), self)
	
	def fromString(self, str):
		sstruct.unpack(sfntDirectoryEntryFormat, str, self)
	
	def toString(self):
		return sstruct.pack(sfntDirectoryEntryFormat, self)
	
	def __repr__(self):
		if hasattr(self, "tag"):
			return "<SFNTDirectoryEntry '%s' at %x>" % (self.tag, id(self))
		else:
			return "<SFNTDirectoryEntry at %x>" % id(self)

class WOFFDirectoryEntry:
    
    def fromFile(self, file):
        sstruct.unpack(woffDirectoryEntryFormat, 
                file.read(woffDirectoryEntrySize), self)
    
    def fromString(self, str):
        sstruct.unpack(woffDirectoryEntryFormat, str, self)
    
    def toString(self):
        return sstruct.pack(woffDirectoryEntryFormat, self)
    
    def __repr__(self):
        if hasattr(self, "tag"):
            return "<WOFFDirectoryEntry '%s' at %x>" % (self.tag, id(self))
        else:
            return "<WOFFDirectoryEntry at %x>" % id(self)

def calcChecksum(data, start=0):
	"""Calculate the checksum for an arbitrary block of data.
	Optionally takes a 'start' argument, which allows you to
	calculate a checksum in chunks by feeding it a previous
	result.
	
	If the data length is not a multiple of four, it assumes
	it is to be padded with null byte. 
	"""
	from fontTools import ttLib
	remainder = len(data) % 4
	if remainder:
		data = data + '\0' * (4-remainder)
	data = struct.unpack(">%dL"%(len(data)/4), data)
	a = numpy.array((start,)+data, numpy.uint32)
	return int(numpy.sum(a,dtype=numpy.uint32))


def maxPowerOfTwo(x):
	"""Return the highest exponent of two, so that
	(2 ** exponent) <= x
	"""
	exponent = 0
	while x:
		x = x >> 1
		exponent = exponent + 1
	return max(exponent - 1, 0)


def getSearchRange(n):
	"""Calculate searchRange, entrySelector, rangeShift for the
	sfnt directory. 'n' is the number of tables.
	"""
	# This stuff needs to be stored in the file, because?
	import math
	exponent = maxPowerOfTwo(n)
	searchRange = (2 ** exponent) * 16
	entrySelector = exponent
	rangeShift = n * 16 - searchRange
	return searchRange, entrySelector, rangeShift

