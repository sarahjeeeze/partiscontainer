"""Script to convert output from partis to required output for the benchmarking tools"""

import csv
import Bio
from Bio.Seq import Seq
from Bio.Alphabet import generic_dna
import pandas as pd
import sys

def csvtotsv(x):

    
    df = pd.read_csv(x)
    newdf = df[['unique_ids', 'invalid','v_gene', 'd_gene', 'j_gene','cdr3_seqs']].copy()
    
    
    df2 = newdf.rename({'unique_ids':'sequence_ids','invalid':'productive',
                        'v_gene':'v_call', 'd_gene':'d_call', 'j_gene':'j_call','cdr3_seqs':'cdr3_aa'}, axis=1)
    df2['productive']*= 1
    df2['productive'].replace({0: True, 1: False}, inplace=True)
    df2['sequence_ids'] = df2['sequence_ids'].str.replace('c',':')

    df2.loc[df2.productive == True, 'cdr3_aa'] = df2['cdr3_aa'].apply(lambda x: (Seq(str(x)).translate()))
   
    df2.to_csv('finalpartis.tsv', sep = '\t')



original = str(sys.argv[1])
csvtotsv(original)
