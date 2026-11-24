# Retrieval evaluation — upstream_contains (live, ncit 26.10d)

queries: 67 (positives 63, negatives 4); errors: 0

| metric | value |
|---|---|
| recall@5 | 0.6667 |
| recall@10 | 0.6667 |
| mrr@10 | 0.6341 |
| ndcg@10 | 0.6412 |
| negativeHitRate | 1.0 |
| latencyP50Ms | 67.7 |
| latencyP95Ms | 130.4 |

| category | n | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|
| anatomy | 5 | 0.8 | 0.8 | 0.8 | 0.8 |
| cde_derived | 6 | 0.1667 | 0.1667 | 0.0417 | 0.0718 |
| concept_name | 15 | 1.0 | 1.0 | 1.0 | 1.0 |
| definition_style | 5 | 0.0 | 0.0 | 0.0 | 0.0 |
| drug | 3 | 1.0 | 1.0 | 1.0 | 1.0 |
| finding | 4 | 1.0 | 1.0 | 1.0 | 1.0 |
| gene | 4 | 0.75 | 0.75 | 0.75 | 0.75 |
| icdo_morphology | 5 | 0.0 | 0.0 | 0.0 | 0.0 |
| icdo_topography | 2 | 0.0 | 0.0 | 0.0 | 0.0 |
| lay_language | 4 | 0.5 | 0.5 | 0.5 | 0.4876 |
| synonym_abbreviation | 10 | 1.0 | 1.0 | 0.87 | 0.9018 |

Misses:
- definition_style-001 'cancer that starts in the plasma cells of bone marrow' expected ['C3242'] got ['C36236', 'C36237', 'C38649', 'C138182', 'C138322']
- definition_style-002 'malignant tumor composed of atypical melanocytes' expected ['C3224'] got ['C121933', 'C146848', 'C155978', 'C156362', 'C167346']
- definition_style-003 'aggressive brain tumor arising from astrocytes, WHO grade IV' expected ['C3058'] got ['C102897', 'C114961', 'C114962', 'C124790', 'C177567']
- definition_style-004 'leukemia with rapid accumulation of immature myeloid cells in the bone marrow' expected ['C3171'] got ['C36237', 'C43220', 'C168679', 'C36236', 'C41061']
- definition_style-005 'malignant epithelial tumor with glandular differentiation' expected ['C2852'] got ['C92647', 'C157714', 'C158620', 'C162724', 'C162725']
- lay_language-003 'blood cancer' expected ['C3161', 'C9300'] got ['C116915', 'C164030', 'C164015', 'C164031', 'C164017']
- lay_language-004 'brain tumor' expected ['C3568', 'C9375'] got ['C2907', 'C157800', 'C157801', 'C214497', 'C157811']
- icdo_morphology-001 '8140/3' expected ['C2852'] got ['C100043', 'C100114', 'C100135', 'C100136', 'C100180']
- icdo_morphology-002 '8720/3' expected ['C3224'] got ['C100043', 'C100114', 'C100135', 'C100136', 'C100180']
- icdo_morphology-003 '9440/3' expected ['C3058'] got ['C100043', 'C100114', 'C100135', 'C100136', 'C100180']
- icdo_morphology-004 '8070/3' expected ['C2929'] got ['C100043', 'C100114', 'C100135', 'C100136', 'C100180']
- icdo_morphology-005 '9861/3' expected ['C3171'] got ['C100043', 'C100114', 'C100135', 'C100136', 'C100180']
- icdo_topography-001 'C34.1' expected ['C12248'] got ['C100000', 'C100002', 'C100041', 'C100088', 'C100089']
- icdo_topography-002 'C50.9' expected ['C12971'] got ['C100189', 'C100200', 'C100224', 'C100259', 'C101904']
- cde_derived-001 'tumor_grade: the degree of abnormality of cancer cells, a measure of differentiation and aggressiveness' expected ['C18000'] got ['C103069', 'C203559', 'C136663', 'C136682', 'C136732']
- cde_derived-002 'race: an arbitrary classification of a taxonomic group that is a division of a species' expected ['C17049'] got ['C131887', 'C160256', 'C105224', 'C106718', 'C107041']
- cde_derived-004 'vital_status: the survival state of the person' expected ['C25717'] got ['C100538', 'C130770', 'C130919', 'C139742', 'C158760']
- cde_derived-005 'sex at birth: the biological sex assigned at birth' expected ['C28421'] got ['C205472', 'C206417', 'C209287', 'C124436', 'C205473']
- cde_derived-006 'days to birth: number of days between index date and date of birth' expected ['C156420'] got ['C181067', 'C181056', 'C181057', 'C181059', 'C181060']
- anatomy-002 'Uvea' expected ['C12775'] got ['C12811', 'C215095', 'C174507', 'C215096', 'C215097']
- gene-001 'BRAF Gene' expected ['C17476'] got ['C18363', 'C133674', 'C154159', 'C40430', 'C148089']
