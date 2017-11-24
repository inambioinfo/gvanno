#!/usr/bin/env python

import csv
import re
import argparse
from itertools import izip, imap
from cyvcf2 import VCF, Writer
import gzip
import dbnsfp
import os
import gvannoutils

logger = gvannoutils.getlogger('gvanno-gene-annotate')
csv.field_size_limit(500 * 1024 * 1024)
threeLettertoOneLetterAA = {'Ala':'A','Arg':'R','Asn':'N','Asp':'D','Cys':'C','Glu':'E','Gln':'Q','Gly':'G','His':'H','Ile':'I','Leu':'L','Lys':'K', 'Met':'M','Phe':'F','Pro':'P','Ser':'S','Thr':'T','Trp':'W','Tyr':'Y','Val':'V','Ter':'X'}


def __main__():
   
   parser = argparse.ArgumentParser(description='Cancer gene annotations from PCGR pipeline (SNVs/InDels)')
   parser.add_argument('vcf_file', help='VCF file with VEP-annotated query variants (SNVs/InDels)')
   parser.add_argument('gvanno_dir',help='PCGR base directory')
   args = parser.parse_args()

   extend_vcf_annotations(args.vcf_file, args.gvanno_dir)

def threeToOneAA(aa_change):
	
	for three_letter_aa in threeLettertoOneLetterAA.keys():
		aa_change = aa_change.replace(three_letter_aa,threeLettertoOneLetterAA[three_letter_aa])

	aa_change = re.sub(r'[A-Z]{1}fsX([0-9]{1,}|\?)','fs',aa_change)
	return aa_change

def map_variant_effect_predictors(rec, algorithms):
    
   dbnsfp_predictions = dbnsfp.map_dbnsfp_predictions(str(rec.INFO.get('DBNSFP').encode('utf-8')), algorithms)
   if rec.INFO.get('Gene') is None or rec.INFO.get('Consequence') is None:
      return
   gene_id = str(rec.INFO.get('Gene').encode('utf-8'))
   consequence = str(rec.INFO.get('Consequence').encode('utf-8'))
     
   dbnsfp_key = ''
     
   if not rec.INFO.get('HGVSp_short') is None:
      aa_change = str(rec.INFO.get('HGVSp_short').encode('utf-8'))
      dbnsfp_key = gene_id + ':' + str(aa_change)
   else:
      if re.search('splice_site',consequence):
         dbnsfp_key = gene_id
   
   if dbnsfp_key != '':
      if dbnsfp_predictions.has_key(dbnsfp_key):
         rec.INFO['EFFECT_PREDICTIONS'] = dbnsfp_predictions[dbnsfp_key]

def set_coding_change(rec):
   
   for m in ['HGVSp_short','CDS_CHANGE']:
      rec.INFO[m] = '.'
   if not rec.INFO.get('HGVSc') is None:
      if rec.INFO.get('HGVSc').encode('utf-8') != '.':
         if 'splice_acceptor_variant' in rec.INFO.get('Consequence').encode('utf-8') or 'splice_donor_variant' in rec.INFO.get('Consequence').encode('utf-8'):
            key = str(rec.INFO.get('Consequence').encode('utf-8')) + ':' + str(rec.INFO.get('HGVSc').encode('utf-8'))
            rec.INFO['CDS_CHANGE'] = key
   if rec.INFO.get('Amino_acids') is None or rec.INFO.get('Protein_position') is None or rec.INFO.get('Consequence') is None:
      return
   if not rec.INFO.get('Protein_position') is None:
      if rec.INFO.get('Protein_position').encode('utf-8').startswith('-'):
         return

   protein_change = '.'
   if '/' in rec.INFO.get('Protein_position').encode('utf-8'):
      protein_position = str(rec.INFO.get('Protein_position').split('/')[0].encode('utf-8'))
      if '-' in protein_position:
         if protein_position.split('-')[0].isdigit():
            rec.INFO['Amino_acid_start'] = protein_position.split('-')[0]
         if protein_position.split('-')[1].isdigit():
            rec.INFO['Amino_acid_end'] = protein_position.split('-')[1]
      else:
         if protein_position.isdigit():
            rec.INFO['Amino_acid_start'] = protein_position
            rec.INFO['Amino_acid_end'] = protein_position
   
   if not rec.INFO.get('HGVSp') is None:
      if rec.INFO.get('HGVSp').encode('utf-8') != '.':
         if ':' in rec.INFO.get('HGVSp').encode('utf-8'):
            protein_identifier = str(rec.INFO.get('HGVSp').encode('utf-8').split(':')[0])
            if protein_identifier.startswith('ENSP'):
               protein_change_VEP = str(rec.INFO.get('HGVSp').encode('utf-8').split(':')[1])
               protein_change = threeToOneAA(protein_change_VEP)
  
   if 'synonymous_variant' in rec.INFO.get('Consequence').encode('utf-8'):
      protein_change = 'p.' + str(rec.INFO.get('Amino_acids').encode('utf-8')) + str(protein_position) + str(rec.INFO.get('Amino_acids').encode('utf-8'))
      if 'stop_lost' in str(rec.INFO.get('Consequence').encode('utf-8')) and '/' in str(rec.INFO.get('Amino_acids').encode('utf-8')):
         protein_change = 'p.X' + str(protein_position) + str(rec.INFO.get('Amino_acids').encode('utf-8')).split('/')[1]
    
   rec.INFO['HGVSp_short'] = protein_change
   exon_number = 'NA'
   if not rec.INFO.get('EXON') is None:
      if rec.INFO.get('EXON').encode('utf-8') != '.':
         if '/' in rec.INFO.get('EXON').encode('utf-8'):
            exon_number = str(rec.INFO.get('EXON').encode('utf-8')).split('/')[0]
  
   if not rec.INFO.get('HGVSc') is None:
      if rec.INFO.get('HGVSc').encode('utf-8') != '.':
         if protein_change != '.':
            key = str(rec.INFO.get('Consequence').encode('utf-8')) + ':' + str(rec.INFO.get('HGVSc').encode('utf-8')) + ':exon' + str(exon_number) + ':' + str(protein_change)
            rec.INFO['CDS_CHANGE'] = key

   return

def write_pass_vcf(annotated_vcf):
   
   out_vcf = re.sub(r'\.annotated\.vcf\.gz$','.annotated.pass.vcf',annotated_vcf)
   vcf = VCF(annotated_vcf)
   w = Writer(out_vcf, vcf)

   num_rejected = 0
   num_pass = 0
   for rec in vcf:
      if rec.FILTER is None or rec.FILTER == 'None':
         w.write_record(rec)
         num_pass += 1
      else:
         num_rejected +=1

   vcf.close()
   w.close()
   
   logger.info('Number of non-PASS/REJECTED variant calls: ' + str(num_rejected))
   logger.info('Number of PASSed variant calls: ' + str(num_pass))
   if num_pass == 0:
      logger.warning('There are zero variants with a \'PASS\' filter in the VCF file')
      os.system('bgzip -dc ' + str(annotated_vcf) + ' egrep \'^#\' > ' + str(out_vcf))
   #else:
   os.system('bgzip -f ' + str(out_vcf))
   os.system('tabix -f -p vcf ' + str(out_vcf) + '.gz')

   return

def extend_vcf_annotations(query_vcf, gvanno_directory):
   """
   Function that reads VEP/vcfanno-annotated VCF and extends the VCF INFO column with tags from
   1. CSQ elements within the primary transcript consequence picked by VEP, e.g. SYMBOL, Feature, Gene, Consequence etc.
   2. Cancer-relevant gene annotations, e.g. known oncogenes/tumor suppressors, known antineoplastic drugs interacting with a given protein etc.
   3. Protein-relevant annotations, e.g. cancer hotspot mutations, functional protein features etc.
   4. Variant effect predictions
   """

   ## read VEP and PCGR tags to be appended to VCF file
   gvanno_vcf_infotags_meta = gvannoutils.read_infotag_file(os.path.join(gvanno_directory,'data','gvanno_infotags.tsv'))
   out_vcf = re.sub(r'\.vcf(\.gz){0,}$','.annotated.vcf',query_vcf)

   vep_to_gvanno_af = {'gnomAD_AMR_AF':'AMR_AF_GNOMAD','gnomAD_AFR_AF':'AFR_AF_GNOMAD','gnomAD_EAS_AF':'EAS_AF_GNOMAD','gnomAD_NFE_AF':'NFE_AF_GNOMAD','gnomAD_AF':'GLOBAL_AF_GNOMAD',
                     'gnomAD_SAS_AF':'SAS_AF_GNOMAD','gnomAD_OTH_AF':'OTH_AF_GNOMAD','gnomAD_ASJ_AF':'ASJ_AF_GNOMAD','gnomAD_FIN_AF':'FIN_AF_GNOMAD','AFR_AF':'AFR_AF_1KG',
                     'AMR_AF':'AMR_AF_1KG','SAS_AF':'SAS_AF_1KG','EUR_AF':'EUR_AF_1KG','EAS_AF':'EAS_AF_1KG', 'AF':'GLOBAL_AF_1KG'}

   vcf = VCF(query_vcf)
   vep_csq_index2fields = {}
   vep_csq_fields2index = {}
   dbnsfp_prediction_algorithms = []
   effect_predictions_description = ""
   for e in vcf.header_iter():
      header_element = e.info()
      if 'ID' in header_element.keys():
         identifier = str(header_element['ID']).encode('utf-8')
         if identifier == 'CSQ' or identifier == 'DBNSFP':
            description = str(header_element['Description']).encode('utf-8')
            if 'Format: ' in description:
               subtags = description.split('Format: ')[1].split('|')
               if identifier == 'CSQ':
                  i = 0
                  for t in subtags:
                     v = t
                     if vep_to_gvanno_af.has_key(t):
                        v = str(vep_to_gvanno_af[t])
                     if gvanno_vcf_infotags_meta.has_key(v):
                        vep_csq_index2fields[i] = v
                        vep_csq_fields2index[v] = i
                     i = i + 1
               if identifier == 'DBNSFP':
                  if len(subtags) > 7:
                     effect_predictions_description = "Format: " + '|'.join(subtags[7:])
                  i = 7
                  while(i < len(subtags)):
                     dbnsfp_prediction_algorithms.append(str(re.sub(r'((_score)|(_pred))"*$','',subtags[i])))
                     i = i + 1
   
   for tag in gvanno_vcf_infotags_meta:
      vcf.add_info_to_header({'ID': tag, 'Description': str(gvanno_vcf_infotags_meta[tag]['description']),'Type':str(gvanno_vcf_infotags_meta[tag]['type']), 'Number': str(gvanno_vcf_infotags_meta[tag]['number'])})
   vcf.add_info_to_header({'ID':'EFFECT_PREDICTIONS', 'Description':'Functional effect predictions from multiple algorithms (dbNSFP)','Type':'String', 'Number':'.'})
   
   w = Writer(out_vcf, vcf)
   vcf_content = []
   current_chrom = None
   num_chromosome_records_processed = 0
   header_printed = 0
   gvanno_xref_map = {'SYMBOL':1, 'ENTREZ_ID':2, 'UNIPROT_ID':3, 'APPRIS':4,'UNIPROT_ACC':5,'CHORUM_ID':6,'TUMOR_SUPPRESSOR':7,'ONCOGENE':8,
                         'DISGENET_CUI':9,'MIM_PHENOTYPE_ID':10,'ONCOSCORE':11}
   for rec in vcf:
      all_transcript_consequences = []
      if current_chrom is None:
         current_chrom = str(rec.CHROM)
         num_chromosome_records_processed = 0
      else:
         if str(rec.CHROM) != current_chrom:
            logger.info('Completed summary of functional annotations for ' + str(num_chromosome_records_processed) + ' variants on chromosome ' + str(current_chrom))
            current_chrom = str(rec.CHROM)
            num_chromosome_records_processed = 0
      if rec.INFO.get('CSQ') is None:
         alt_allele = ','.join(rec.ALT).encode('utf-8')
         pos = rec.start + 1
         variant_id = 'g.' + str(rec.CHROM) + ':' + str(pos) + str(rec.REF) + '>' + alt_allele
         logger.warning('Variant record ' + str(variant_id) + ' does not have CSQ tag from Variant Effect Predictor (vep_skip_intergenic in config set to true?)  - variant will be skipped')
         continue
      gvanno_xref = {}
      num_chromosome_records_processed += 1
      if not rec.INFO.get('GVANNO_XREF') is None:
         for transcript_onco_xref in rec.INFO.get('GVANNO_XREF').encode('utf-8').split(','):
            xrefs = transcript_onco_xref.split('|')
            ensembl_transcript_id = str(xrefs[0])
            gvanno_xref[ensembl_transcript_id] = {}
            for annotation in gvanno_xref_map.keys():
               annotation_index = gvanno_xref_map[annotation]
               if annotation_index > (len(xrefs) - 1):
                  continue
               if xrefs[annotation_index] != '':
                  gvanno_xref[ensembl_transcript_id][annotation] = xrefs[annotation_index]
      for identifier in ['CSQ','DBNSFP']:
         if identifier == 'CSQ':
            num_picks = 0
            for csq in rec.INFO.get(identifier).encode('utf-8').split(','):
               csq_fields =  csq.split('|')
               if csq_fields[vep_csq_fields2index['PICK']] == "1": ## only consider the primary/picked consequence when expanding with annotation tags
                  num_picks += 1
                  j = 0
                  ## loop over all CSQ elements and set them in the vep_info_tags dictionary (for each alt_allele)
                  while(j < len(csq_fields)):
                     if vep_csq_index2fields.has_key(j):
                        if csq_fields[j] != '':
                           rec.INFO[vep_csq_index2fields[j]] = str(csq_fields[j])
                           if vep_csq_index2fields[j] == 'Feature':
                              ensembl_transcript_id = str(csq_fields[j])
                              if gvanno_xref.has_key(ensembl_transcript_id):
                                 for annotation in gvanno_xref_map.keys():
                                    if annotation == 'UNIPROT_ACC' or annotation == 'SYMBOL':
                                       continue
                                    if gvanno_xref[ensembl_transcript_id].has_key(annotation):
                                       if annotation == 'TUMOR_SUPPRESSOR' or annotation == 'ONCOGENE':
                                          rec.INFO[annotation] = True
                                       else:
                                          rec.INFO[annotation] = gvanno_xref[ensembl_transcript_id][annotation]
                           
                     j = j + 1
                  set_coding_change(rec)
               symbol = '.'
               if csq_fields[vep_csq_fields2index['SYMBOL']] != "":
                  symbol = str(csq_fields[vep_csq_fields2index['SYMBOL']])
               consequence_entry = str(csq_fields[vep_csq_fields2index['Consequence']]) + ':' + str(symbol) + ':' + str(csq_fields[vep_csq_fields2index['Feature_type']]) + ':' + str(csq_fields[vep_csq_fields2index['Feature']]) + ':' + str(csq_fields[vep_csq_fields2index['BIOTYPE']])
               all_transcript_consequences.append(consequence_entry)

         if identifier == 'DBNSFP':
            if not rec.INFO.get('DBNSFP') is None:
               map_variant_effect_predictors(rec, dbnsfp_prediction_algorithms)
      rec.INFO['VEP_ALL_CONSEQUENCE'] = ','.join(all_transcript_consequences)
      w.write_record(rec)
   w.close()
   logger.info('Completed summary of functional annotations for ' + str(num_chromosome_records_processed) + ' variants on chromosome ' + str(current_chrom))
   vcf.close()

   if os.path.exists(out_vcf):
      if os.path.getsize(out_vcf) > 0:
         os.system('bgzip -f ' + str(out_vcf))
         os.system('tabix -f -p vcf ' + str(out_vcf) + '.gz')
         annotated_vcf = out_vcf + '.gz'
         write_pass_vcf(annotated_vcf)
      else:
         gvannoutils.gvanno_error_message('No remaining PASS variants found in query VCF - exiting and skipping STEP 4 (gvanno-writer)', logger)
   else:
      gvannoutils.gvanno_error_message('No remaining PASS variants found in query VCF - exiting and skipping STEP 4 (gvanno-writer)', logger)

if __name__=="__main__": __main__()


      
