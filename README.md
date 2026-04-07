<<<<<<< HEAD
# IARC-SMILES

The International Agency for Research on Cancer (IARC) is a specialized cancer research agency of the World Health Organization that evaluates the carcinogenic risk of substances, mixtures, and exposure circumstances to humans. IARC organizes its assessments into classification groups ranging from Group 1 (carcinogenic to humans) through Group 4 (probably not carcinogenic to humans), based on the strength of available scientific evidence. SMILES (Simplified Molecular-Input Line-Entry System) is a widely used chemical notation that encodes molecular structures as compact ASCII strings, enabling easy storage, searching, and exchange of chemical data. This repository contains IARC-classified carcinogen lists converted into SMILES format, making it straightforward to use the data in cheminformatics workflows and chemical databases. The data was obtained by scraping official IARC sources and then standardizing each entry into a machine-readable SMILES representation.

List is updated monthly through github ci.
=======
# IARC SMILES

Auto-scraped [IARC Monographs](https://monographs.iarc.who.int/list-of-classifications/) carcinogen classifications with canonical SMILES notation from [PubChem](https://pubchem.ncbi.nlm.nih.gov/).

Updated weekly via GitHub Actions CI.

## IARC Groups

| Group | Classification |
|-------|---------------|
| **1** | Carcinogenic to humans |
| **2A** | Probably carcinogenic to humans |
| **2B** | Possibly carcinogenic to humans |
| **3** | Not classifiable as to its carcinogenicity to humans |

## Data

Files in `data/` are tab-separated `.smi` files:

```
SMILES<TAB>Original_IARC_Name
```

- `data/group1.smi` — Group 1 agents
- `data/group2a.smi` — Group 2A agents
- `data/group2b.smi` — Group 2B agents
- `data/group3.smi` — Group 3 agents
- `data/failed_lookups.txt` — Agents without a SMILES match (mixtures, occupational exposures, biological agents, etc.)

Entries are deduplicated by SMILES within each group and sorted alphabetically by agent name.

## How it works

`scripts/scrape.py` uses headless Firefox (Selenium) to scrape the IARC classifications table, then queries the PubChem REST API to resolve each chemical agent to a canonical SMILES string. Multiple name-cleaning heuristics are applied to maximize match rates.

The scraper supports incremental updates — existing `.smi` files are loaded first and only new agents are looked up.

## Downstream

This data feeds into [etoxpred-examples](https://github.com/morawskidotmy/etoxpred-examples) for toxicity prediction with eToxPred.
>>>>>>> 26c18f3 ( first commit)
