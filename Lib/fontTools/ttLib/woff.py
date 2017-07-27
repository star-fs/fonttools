"""ttLib/woff.py -- low-level module to deal with the woff file format.

Defines two public classes:
	WOFFReader
	WOFFWriter

(Normally you don't have to use these classes explicitly; they are 
used automatically by ttLib.TTFont.)

The reading and writing of woff files is separated in two distinct 
classes, since whenever to number of tables changes or whenever
a table's length chages you need to rewrite the whole file anyway.
"""

import sys
import struct, sstruct
import numpy
import os
import zlib

class WOFFReader:
	
	def __init__(self, file, checkChecksums=1):
		self.file = file
		self.checkChecksums = checkChecksums

		# reset the file handle
		self.file.seek(0)

		data = self.file.read(woffHeaderSize)

		if len(data) <> woffHeaderSize:
			from fontTools import ttLib
			raise ttLib.TTLibError, "Not a WOFF font (not enough data)"

		sstruct.unpack(woffHeaderFormat, data, self)
		print "woff flavor '%s'" % self.wOFFflavor

		if self.wOFFflavor not in ("\000\001\000\000", "OTTO", "true"):
			from fontTools import ttLib
			raise ttLib.TTLibError, "Not WOFF encapsulated TrueType or OpenType font (bad flavor)"
		self.tables = {}
		for i in range(self.wOFFnumTables):
			entry = WOFFDirectoryEntry()
			entry.fromFile(self.file)
			if entry.origLength > 0:
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

                if entry.compLength == entry.origLength:
        		data = self.file.read(entry.compLength)
                else:
                        data = zlib.decompress(self.file.read(entry.compLength))

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


class WOFFWriter:
	
	def __init__(self, file, numTables, woffVersion="\000\001\000\000"):
		self.file = file
		self.numTables = numTables
		self.woffVersion = woffVersion
		self.searchRange, self.entrySelector, self.rangeShift = getSearchRange(numTables)
		self.nextTableOffset = woffDirectorySize + numTables * woffDirectoryEntrySize
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
			entry = WOFFDirectoryEntry()
			entry.tag = tag
			entry.offset = self.nextTableOffset
			entry.length = len(data)
			self.nextTableOffset = self.nextTableOffset + ((len(data) + 3) & ~3)
		self.file.seek(entry.offset)
		self.file.write(data)
		self.file.seek(self.nextTableOffset)
		# make sure we're actually where we want to be. (XXX old cStringIO bug)
		self.file.write('\0' * (self.nextTableOffset - self.file.tell()))
		
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
		
		directory = sstruct.pack(woffHeaderFormat, self)
		
		self.file.seek(woffDirectorySize)
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
		checksums = numpy.zeros(len(tags)+1, numpy.int32)
		for i in range(len(tags)):
			checksums[i] = self.tables[tags[i]].checkSum
		
		directory_end = woffDirectorySize + len(self.tables) * woffDirectoryEntrySize
		assert directory_end == len(directory)
		
		checksums[-1] = calcChecksum(directory)
		checksum = numpy.add.reduce(checksums)
		# BiboAfba!
		checksumadjustment = numpy.array(0xb1b0afbaL - 0x100000000L,
				numpy.int32) - checksum
		# write the checksum to the file
		self.file.seek(self.tables['head'].offset + 8)
		self.file.write(struct.pack(">l", checksumadjustment))


# -- woff directory helpers and cruft
woffHeaderFormat = """
		> # big endian
		wOFFsignature:       4s # 0x774F4646 'wOFF'
		wOFFflavor:          I  # The "sfnt version" 0x00010000 for TrueType or 0x4F54544F 'OTTO' for CFF
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
		tag:	      4s # 4-byte sfnt table identifier.
		offset:       I  # Offset to the data, from beginning of WOFF file.
		compLength:   I  # Length of the compressed data, excluding padding.
		origLength:   I  # Length of the uncompressed table, excluding padding.
		origChecksum: I  # Checksum of the uncompressed table.
"""
woffDirectoryEntrySize = sstruct.calcsize(woffDirectoryEntryFormat)

#woffDirectoryEntryFormat = """
#		> # big endian
#		tag:            4s
#		checkSum:       l
#		offset:         l
#		length:         l
#"""


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
	a = numpy.fromstring(struct.pack(">l", start) + data, numpy.int32)
	if sys.byteorder <> "big":
		a = a.byteswap()
	return numpy.add.reduce(a)


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
	woff directory. 'n' is the number of tables.
	"""
	# This stuff needs to be stored in the file, because?
	import math
	exponent = maxPowerOfTwo(n)
	searchRange = (2 ** exponent) * 16
	entrySelector = exponent
	rangeShift = n * 16 - searchRange
	return searchRange, entrySelector, rangeShift

