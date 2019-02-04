#!/usr/bin/env python

import csv
import re
import argparse
from cyvcf2 import VCF, Writer
import gzip
import os
import annoutils

logger = annoutils.getlogger('gvanno-gene-annotate')
csv.field_size_limit(500 * 1024 * 1024)


def __main__():
   
   parser = argparse.ArgumentParser(description='Gene annotations from gvanno pipeline (SNVs/InDels)')
   parser.add_argument('vcf_file', help='VCF file with VEP-annotated query variants (SNVs/InDels)')
   parser.add_argument('gvanno_db_dir',help='gvanno data directory')
   parser.add_argument('lof_prediction',default=0,type=int,help='VEP LoF prediction setting (0/1)')
   args = parser.parse_args()

   extend_vcf_annotations(args.vcf_file, args.gvanno_db_dir, args.lof_prediction)

def extend_vcf_annotations(query_vcf, gvanno_db_directory, lof_prediction = 0):
   """
   Function that reads VEP/vcfanno-annotated VCF and extends the VCF INFO column with tags from
   1. CSQ elements within the primary transcript consequence picked by VEP, e.g. SYMBOL, Feature, Gene, Consequence etc.
   2. Gene annotations, e.g. known oncogenes/tumor suppressors, curated disease associations (DisGenet), MIM phenotype associations etc
   3. Protein-relevant annotations, e.g. c functional protein features etc.
   4. Variant effect predictions
   """

   ## read VEP and PCGR tags to be appended to VCF file
   vcf_infotags_meta = annoutils.read_infotag_file(os.path.join(gvanno_db_directory,'gvanno_infotags.tsv'))
   out_vcf = re.sub(r'\.vcf(\.gz){0,}$','.annotated.vcf',query_vcf)

   meta_vep_dbnsfp_info = annoutils.vep_dbnsfp_meta_vcf(query_vcf, vcf_infotags_meta)
   vep_csq_index2fields = meta_vep_dbnsfp_info['vep_csq_index2fields']
   vep_csq_fields2index = meta_vep_dbnsfp_info['vep_csq_fields2index']
   dbnsfp_prediction_algorithms = meta_vep_dbnsfp_info['dbnsfp_prediction_algorithms']

   vcf = VCF(query_vcf)
   for tag in vcf_infotags_meta:
      if lof_prediction == 0:
         if not tag.startswith('LoF'):
            vcf.add_info_to_header({'ID': tag, 'Description': str(vcf_infotags_meta[tag]['description']),'Type':str(vcf_infotags_meta[tag]['type']), 'Number': str(vcf_infotags_meta[tag]['number'])})
      else:
         vcf.add_info_to_header({'ID': tag, 'Description': str(vcf_infotags_meta[tag]['description']),'Type':str(vcf_infotags_meta[tag]['type']), 'Number': str(vcf_infotags_meta[tag]['number'])})

   
   w = Writer(out_vcf, vcf)
   current_chrom = None
   num_chromosome_records_processed = 0
   gvanno_xref_map = {'ENSEMBL_TRANSCRIPT_ID':0, 'ENSEMBL_GENE_ID':1, 'SYMBOL':2, 'ENTREZ_ID':3, 'UNIPROT_ID':4, 'APPRIS':5,'UNIPROT_ACC':6,
                        'REFSEQ_MRNA':7, 'CORUM_ID':8,'TUMOR_SUPPRESSOR':9,'ONCOGENE':10,'DISGENET_CUI':11,'MIM_PHENOTYPE_ID':12}
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
         alt_allele = ','.join(rec.ALT)
         pos = rec.start + 1
         variant_id = 'g.' + str(rec.CHROM) + ':' + str(pos) + str(rec.REF) + '>' + alt_allele
         logger.warning('Variant record ' + str(variant_id) + ' does not have CSQ tag from Variant Effect Predictor (vep_skip_intergenic in config set to true?)  - variant will be skipped')
         continue
      gvanno_xref = {}
      num_chromosome_records_processed += 1
      if not rec.INFO.get('GVANNO_XREF') is None:
         for transcript_xref in rec.INFO.get('GVANNO_XREF').split(','):
            xrefs = transcript_xref.split('|')
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
            for csq in rec.INFO.get(identifier).split(','):
               csq_fields =  csq.split('|')
               if csq_fields[vep_csq_fields2index['PICK']] == "1": ## only consider the primary/picked consequence when expanding with annotation tags
                  num_picks += 1
                  j = 0
                  ## loop over all CSQ elements and set them in the vep_info_tags dictionary (for each alt_allele)
                  while(j < len(csq_fields)):
                     if j in vep_csq_index2fields:
                        if csq_fields[j] != '':
                           rec.INFO[vep_csq_index2fields[j]] = str(csq_fields[j])
                           if vep_csq_index2fields[j] == 'Feature':
                              ensembl_transcript_id = str(csq_fields[j])
                              if ensembl_transcript_id in gvanno_xref:
                                 for annotation in gvanno_xref_map.keys():
                                    if annotation in gvanno_xref[ensembl_transcript_id]:
                                       if annotation == 'TUMOR_SUPPRESSOR' or annotation == 'ONCOGENE':
                                          rec.INFO[annotation] = True
                                       else:
                                          rec.INFO[annotation] = gvanno_xref[ensembl_transcript_id][annotation]
                           if vep_csq_index2fields[j] == 'DOMAINS':
                              domain_identifiers = str(csq_fields[j]).split('&')
                              for v in domain_identifiers:
                                 if v.startswith('Pfam_domain'):
                                    rec.INFO['PFAM_DOMAIN'] = str(re.sub(r'\.[0-9]{1,}$','',re.sub(r'Pfam_domain:','',v)))

                           if vep_csq_index2fields[j] == 'Existing_variation':
                              var_identifiers = str(csq_fields[j]).split('&')
                              cosmic_identifiers = []
                              dbsnp_identifiers = []
                              for v in var_identifiers:
                                 if v.startswith('COSM'):
                                    cosmic_identifiers.append(v)
                                 if v.startswith('rs'):
                                    dbsnp_identifiers.append(v)
                              if len(cosmic_identifiers) > 0:
                                 rec.INFO['COSMIC_MUTATION_ID'] = '&'.join(cosmic_identifiers)
                              if len(dbsnp_identifiers) > 0:
                                 rec.INFO['DBSNPRSID'] = '&'.join(dbsnp_identifiers)
                           
                     j = j + 1
                  annoutils.set_coding_change(rec)
               symbol = '.'
               if csq_fields[vep_csq_fields2index['SYMBOL']] != "":
                  symbol = str(csq_fields[vep_csq_fields2index['SYMBOL']])
               consequence_entry = str(csq_fields[vep_csq_fields2index['Consequence']]) + ':' + str(symbol) + ':' + str(csq_fields[vep_csq_fields2index['Feature_type']]) + ':' + str(csq_fields[vep_csq_fields2index['Feature']]) + ':' + str(csq_fields[vep_csq_fields2index['BIOTYPE']])
               all_transcript_consequences.append(consequence_entry)

         if identifier == 'DBNSFP':
            if not rec.INFO.get('DBNSFP') is None:
               annoutils.map_variant_effect_predictors(rec, dbnsfp_prediction_algorithms)
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
         annoutils.write_pass_vcf(annotated_vcf, logger)
      else:
         annoutils.error_message('No remaining PASS variants found in query VCF - exiting and skipping STEP 4 (gvanno-writer)', logger)
   else:
      annoutils.error_message('No remaining PASS variants found in query VCF - exiting and skipping STEP 4 (gvanno-writer)', logger)

if __name__=="__main__": __main__()


      
