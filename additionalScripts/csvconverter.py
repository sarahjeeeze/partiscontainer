import csv
 
import pandas as pd

#need to update a little 

import sys

def csvtotsv(x):

    
    df = pd.read_csv(x)
    newdf = df[['unique_ids', 'invalid','v_gene', 'd_gene', 'j_gene','cdr3_seqs']].copy()
    


    newdf.to_csv('finalpartis.tsv', sep = '\t')



original = str(sys.argv[1])
csvtotsv(original)
