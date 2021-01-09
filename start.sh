#!/bin/bash

#change these to the volumes! eg. make the volumes sampledata/input etc and change these to just input/output/germlines
INPUT_DIR=/INPUT
OUTPUT_DIR=/OUTPUT
GERMLINE_DIR=/GERMLINE

GERMLINE_BUILD_DIR=/GERMLINE_BUILD_DIR
mkdir -p $GERMLINE_BUILD_DIR
#temporary while i need to clarify a few things with Erand
#INPUT_FASTA= /INPUT/sample.fasta


correct_usage()
{
		partis/additionalScripts/tools/correct_usage.txt

}
if [ -z "$1" ]
then 
	echo "SPECIES not provided. Will exit."
	correct_usage
	exit 2 
else 
	SPECIES=$1
fi

if [ -z "$2" ]
then
	
	echo "RECEPTOR not provided. Will exit."
	correct_usage
	exit 2 
else
	RECEPTOR=$2
fi
	

collect_fastas()
{
	the_path=$1
	the_output=$2
	the_pattern=$3

	FQ_LIST='find $the_path -type f -name "$the_pattern"'

	size=${#FQ_LIST}
	
	
}



collect_fastas $INPUT_DIR $INPUT_DIR "*.fasta"
#this converts IMGT germline to Partis germline but not actually using the germline output yet because of extras file confusion.
cp -R $GERMLINE_DIR $GERMLINE_BUILD_DIR
python /partis/additionalScripts/germlineToPartis.py $GERMLINE_BUILD_DIR/GERMLINE $SPECIES

NR_FASTA=$(cat $INPUT_DIR | wc -l)
for filename in "$INPUT_DIR"/*; do
	echo "Processing file: $filename"
	echo ""
		echo ""
		COMMAND="python ../partis/bin/partis annotate --infname /INPUT/sample.fasta --initial-germline-dir /GERMLINE_BUILD_DIR/partis --locus $RECEPTOR --extra-annotation-columns cdr3_seqs --outfname $OUTPUT_DIR/partis.csv"
		echo ""
		eval $COMMAND
	done


for filename in "$OUTPUT_DIR"/*; do
	echo "Processing file: $filename"
	echo ""
		COMMAND="python /partis/additionalScripts/csvconverter.py $filename"
		echo ""

		eval $COMMAND
	done



cp /partis/finalpartis.tsv /OUTPUT	
