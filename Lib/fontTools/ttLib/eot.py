"""ttLib/eot.py -- low-level module to deal with the EOT-lite file format.

Defines two public classes:
	EOTReader
	EOTWriter

(Normally you don't have to use these classes explicitly; they are 
used automatically by ttLib.TTFont.)

The reading and writing of eot files is separated in two distinct 
classes, since whenever to number of tables changes or whenever
a table's length chages you need to rewrite the whole file anyway.
"""

import sys
import struct, sstruct
import numpy
import os
import zlib
from sfnt import SFNTReader
from sfnt import SFNTWriter

class EOTReader(SFNTReader):
	
	def __init__(self, file, checkChecksums=1):
		self.file = file
		self.checkChecksums = checkChecksums
		eot_data = self.file.read(eotHeaderSize)
		sstruct.unpack(eotHeaderFormat, eot_data, self)
                self.file.seek(self.EOTSize - self.EOTFontDataSize)
                self.EOTHeaderLen = self.EOTSize - self.EOTFontDataSize
		SFNTReader.__init__(self, file, checkChecksums=1)

        def __getitem__(self, tag):
                """Fetch the raw table data."""
                entry = self.tables[tag]

                self.file.seek(entry.offset + self.EOTHeaderLen)
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


class EOTWriter(SFNTWriter):
	
	def __init__(self, file, numTables, sfntVersion="\000\001\000\000"):
		SFNTWriter.__init__(self, file, numTables, sfntVersion="\000\001\000\000")	


# -- eot directory helpers and cruft
eotHeaderFormat = """
		= # big endian
		EOTSize:	     L  # Total structure length in bytes (including string and font data)
		EOTFontDataSize:     L  # Length of the OpenType font (FontData) in bytes
		EOTVersion:	     L  # Version number
		EOTFlags:	     L  # Processing flags
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTPadding1: 	     H # blah
		EOTMagicNumber:      H  # Magic number for EOT file - 0x504C
"""

eotHeaderSize = sstruct.calcsize(eotHeaderFormat)

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


