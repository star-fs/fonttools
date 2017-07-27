#! /usr/bin/env python
import sys 
import os
import getopt
import re
from fontTools.ttLib import TTFont

def main(args):

	outfile = ""

	# get options and files
	try:
		rawOptions, files = getopt.getopt(sys.argv[1:], "o:d:")
		options = Options(rawOptions)
	except getopt.GetoptError:
		print getopt.GetoptError
	if not files:
		print "ttf2woff [-d outdir] [-O outfile] ttf_file"
		sys.exit(2)

	for infile in files:
		type = guessFileType(infile)

	if type == None:
		print "please use only truetype files"
		sys.exit(3)

	print "opened '%s' (type %s) for reading" % (infile, type)

	if options.outfile == "":
		base, ext = os.path.splitext(infile)
		options.outfile = base + ".woff"

	outfile = open(options.outfile, "wb")
	if hasattr(outfile, "write"):
		print "opened '%s' for writing" % options.outfile

	# open the file
	ttf = TTFont(infile, 0, "", "","","",type=type)
	ttf.saveWoff(outfile)
	

def guessFileType(fileName):
    base, ext = os.path.splitext(fileName)
    try:
        f = open(fileName, "rb")
    except IOError:
        return None

    if ext == ".dfont":
        return "TTF"

    header = f.read(256)
    head = header[:4]
    if head in ("\0\1\0\0", "true"):
        return "TTF"

	if head == "OTTO":
		return "OTF"

	if head == "ttcf":
		return "TTC"

	if head in ("\0\1\0\0", "true"):
		return "TTF"

	if head == "wOFF":
		return "WOFF"

	if head.lower() == "<?xm":
		if header.find('sfntVersion="OTTO"') > 0:
			return "OTX"
		else:
			return "TTX"

	return None

class Options:
	outdir = ""
	outfile = ""
	def __init__(self, rawOptions):
		for option, value in rawOptions:
			if option == "-o":
				self.outfile = value
			elif option == "-d":
				if not os.path.isdir(value):
					print "The -d option value must be an existing directory"
					sys.exit(4)
				else:
					self.outdir = value

if __name__ == "__main__":
    main(sys.argv[1:])
