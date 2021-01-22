"""Script to change format of Germline to the one required for Partis """

from __future__ import absolute_import
from __future__ import with_statement
import os, shutil
from os import path
import time
from io import open
import csv
import sys
import re
from shutil import copyfile

directory = str(sys.argv[1])

species = str(sys.argv[2])

available_species = ['ch17','mouse','human','macaque','chicken']

if species in available_species:
    species = species
else:
    species = 'human'


print u"Executing germline format conversion..."
def convert(x):
    u"""Fuction to convert IMGT fasta format to that expected in Partis
    Input: file name as a string
    Output: newfile saved in folders """
    
    imgtFasta = open(unicode(x)).read()
    p = re.compile(r'>.+?\|(.+?)\|',flags=re.UNICODE)
    genes = p.findall(imgtFasta)
    imgtFasta = imgtFasta.replace('\n', '')
    imgtFasta = imgtFasta.replace('.', '')
    imgtFasta = imgtFasta + '>'
    l = re.compile(r'\|([nacgt].+?)>',flags=re.UNICODE)
    seq = l.findall(imgtFasta)
    final = ''
    
    if (len(genes)-1)>0:
        
        for i in xrange(0,(len(genes)-1)):
            final = final + u'>' + genes[i] + '\n' + seq[i].upper() + '\n'
            new_file = unicode(x) 

            text_file = open(new_file, u"w")
            text_file.write(final)
            text_file.close()
    else:
            final = final + '>' + genes[0] + '\n' + seq[0].upper() + '\n'
            new_file = unicode(x) 

            text_file = open(new_file, u"w")
            text_file.write(final)
            text_file.close()
    

#apply to relevant files in folder
names = ['constant','leader','vdj']
for file in names:
    for filename in os.listdir(directory + '/' + file):
        
        convert(directory + '/'  + file +  '/' + filename)
     


os.chdir(directory)
os.mkdir(directory + "/../partis")
src = directory + '/vdj'
def rename(x):
    """function to change name of all the files

    Input: directory (relative)
    Output: renames files within the directory
    """
    
    for i in os.listdir(unicode(x)):
        newname = (unicode(i[-10:-6]).lower() + u'.fasta') 
        
        os.rename(src+u"/"+i,
              src+u"/"+newname)

#apply rename function to all files
rename(src)

os.chdir(directory + "/../partis")
def make_folders():
    """function to make the folders to match that required by partis

    Input: nothing
    Output: set of empty folders"""
    files = [u'igh',u'igk',u'igl',u'imgt-alignments',u'tra',u'trb',u'trd',u'trg']

    for file in files:
        os.mkdir(file)

#call the function
make_folders()

#put relevant files in to relevant folders
def reorder_files():
    """function to file all the fasta files in to respective folders
    Input: nothing
    Output: folders containing relevant fasta files """
    files = [u'igh',u'igk',u'igl',u'tra',u'trb',u'trd',u'trg']

    src = os.path.join(directory,'vdj')
    src2 = os.path.join(directory)
    for file in files:
        
        dst = os.path.join(src2,u'..','partis',file)
        fastas = [i for i in os.listdir(src) if unicode(file.lower())in i]
        for f in fastas:
                
                shutil.copy(os.path.join(src, f), dst)
#call the function

reorder_files()
def move_vdj_aa():
    """function to move vdj alignment files in to correct folder structure required for partis"""
    src = os.path.join(directory,'vdj_aa')
    src2 = os.path.join(directory,'/../partis')
    dst = os.path.join(src2,'imgt-alignments')
    for file in os.listdir(src):
              shutil.copy(os.path.join(src,file),dst)
def rename_vdj():
    """function to rename vdj alignment files to what is expected of partis"""
    src = os.path.join(directory,'vdj_aa')
    src2 = os.path.join(directory)
    dst = os.path.join(src2,'..','partis','imgt-alignments')
    for i in os.listdir(dst):
        newname = (unicode(i[-10:-7]).lower() + u'.fasta') 
        
        os.rename(dst+u'/'+i,
                  dst+u'/'+newname)

def copy_extras():
        src = os.path.join(directory,'..','partis')
        files = [u'igh',u'igk',u'igl',u'tra',u'trb',u'trd',u'trg']
        
        original = os.path.join(directory,'..','..','..','partis','data','germlines',str(species))
        for original_file in files:
            source = os.path.join(original,original_file,'extras.csv')
            destination = os.path.join(src,original_file)
            shutil.copy(source,destination)
move_vdj_aa()
rename_vdj()
copy_extras()

print u"Completed germline format conversion"
