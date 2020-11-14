#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Read a PHYLIP-format file and produce an appropriate config file for passing to `dnapars`.

`dnapars` is a rather old program that doesn't play very well in a
pipeline.  It prompts the user for configuration information and reads
responses from stdin.  The config file generated by this script is
meant to mimic the responses to the expected prompts.

Typical usage is,

     $ phylip_parse.py sequence.phy > dnapars.cfg
     $ dnapars <dnapars.cfg

For reference, the dnapars configuration prompt looks like this:
____________
Please enter a new file name> dummy.phylip

DNA parsimony algorithm, version 3.696

Setting for this run:
  U                 Search for best tree?  Yes
  S                        Search option?  More thorough search
  V              Number of trees to save?  10000
  J   Randomize input order of sequences?  No. Use input order
  O                        Outgroup root?  No, use as outgroup species  1
  T              Use Threshold parsimony?  No, use ordinary parsimony
  N           Use Transversion parsimony?  No, count all steps
  W                       Sites weighted?  No
  M           Analyze multiple data sets?  No
  I          Input sequences interleaved?  Yes
  0   Terminal type (IBM PC, ANSI, none)?  ANSI
  1    Print out the data at start of run  No
  2  Print indications of progress of run  Yes
  3                        Print out tree  Yes
  4          Print out steps in each site  No
  5  Print sequences at all nodes of tree  No
  6       Write out trees onto tree file?  Yes

  Y to accept these or type the letter for one to change
____________

"""
import re, os, random
import argparse
from warnings import warn

def main():

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('phylip', help='PHYLIP input', type=str)
    parser.add_argument('treeprog', help='dnaml or dnapars', type=str)
    parser.add_argument('--quick', action='store_true', help='quicker (less thourough) dnapars')
    parser.add_argument('--bootstrap', type=int, default=0, help='input is seqboot output with this many samples')
    args = parser.parse_args()

    print(os.path.realpath(args.phylip))		# phylip input file
    if args.treeprog == 'seqboot':
        print('R')
        print(args.bootstrap)
        print('Y')
        print(str(1+2*random.randint(0, 1000000))) # random seed for bootstrap (odd integer)
        return
    print('J')
    print(str(1+2*random.randint(0, 1000000)))
    print('10')
    if args.bootstrap:
        print('M')
        print('D')
        print(args.bootstrap)
    if args.treeprog == 'dnapars':
        print("O")						# Outgroup root
        print(1)		# arbitrary root on first
        if args.quick:
            print('S')
            print('Y')
        print('4')
        print('5')
        print('.')
        print('Y')
    elif args.treeprog == 'dnaml':
        print("O")						# Outgroup root
        print(1)		# arbitrary root on first
        print("R") # gamma
        print("5")                                         # Reconstruct hypothetical seq
        print("Y")                                         # accept these
        print("1.41421356237") # CV = sqrt(2) (alpha = .5)
        print("4") # 4 catagories
    else:
        raise RuntimeError('treeprog='+args.treeprog+' is not "dnaml", "dnapars", or "seqboot"')


if __name__ == "__main__":
   main()