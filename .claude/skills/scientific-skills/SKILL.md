---
name: scientific-skills
model: claude-haiku-4-5
description: |
  Collection of 176 scientific computing, bioinformatics, cheminformatics, data science,
  and research tools. Use when working with scientific databases, analysis libraries,
  lab automation, or research workflows. Trigger by naming the specific tool or domain
  (e.g. "use rdkit", "query pubmed", "analyze with scanpy", "run DESeq2").
---

You are a router for 176 scientific computing, bioinformatics, cheminformatics, and data science child skills.

## When to Use
- User names a specific scientific tool or library (e.g. "use rdkit", "query pubmed")
- Working with genomics, proteomics, or cheminformatics data
- Need to analyze data with scientific Python libraries (scanpy, polars, statsmodels)
- Lab automation or research workflow tasks
- Literature search, citation management, or paper analysis

## Output
- Routes to the appropriate child skill with its own SKILL.md and references
- Provides category-level guidance when no exact child skill matches

# Scientific Skills Collection

176 child skills covering scientific databases, Python libraries, lab automation, and research workflows.

## How to Use

Reference a child skill by name. Each has its own `SKILL.md` and `references/` docs:

```
scientific-skills/<skill-name>/SKILL.md
scientific-skills/<skill-name>/references/
```

## Categories

### Genomics & Bioinformatics
`biopython` `pysam` `deeptools` `gget` `scikit-bio` `polars-bio` `anndata` `scanpy`
`scvi-tools` `scvelo` `cellxgene-census` `arboreto` `gtars` `tiledbvcf` `flowio`
`pydeseq2` `aeon` `neuropixels-analysis` `neurokit2` `lamindb` `latchbio-integration`
`dnanexus-integration` `networkx`

### Genomic & Molecular Databases
`pubmed-database` `uniprot-database` `alphafold-database` `pdb-database` `ensembl-database`
`gene-database` `gnomad-database` `gwas-database` `clinvar-database` `clinpgx-database`
`gtex-database` `geo-database` `ena-database` `reactome-database` `kegg-database`
`string-database` `cbioportal-database` `cosmic-database` `depmap` `monarch-database`
`interpro-database` `jaspar-database` `hmdb-database` `metabolomics-workbench-database`
`imaging-data-commons`

### Cheminformatics & Drug Discovery
`rdkit` `chembl-database` `drugbank-database` `pubchem-database` `zinc-database`
`bindingdb-database` `brenda-database` `deepchem` `molfeat` `datamol` `diffdock`
`medchem` `pytdc` `cobrapy` `matchms` `glycoengineering` `dhdna-profiler` `adaptyv`
`esm` `rowan` `ginkgo-cloud-lab`

### Machine Learning & Deep Learning
`scikit-learn` `scikit-survival` `torch-geometric` `torchdrug` `pytorch-lightning`
`transformers` `stable-baselines3` `pufferlib` `shap` `umap-learn` `vaex`
`timesfm-forecasting` `modal`

### Quantum Computing
`qiskit` `cirq` `pennylane` `qutip`

### Data Analysis & Visualization
`polars` `dask` `statsmodels` `pymc` `sympy` `matplotlib` `seaborn` `plotly`
`exploratory-data-analysis` `statistical-analysis`

### Lab Automation & Integration
`opentrons-integration` `pylabrobot` `benchling-integration` `omero-integration`
`protocolsio-integration` `labarchive-integration`

### Imaging & Pathology
`histolab` `pathml` `pydicom`

### Geospatial & Earth Science
`geopandas` `astropy` `geomaster` `datacommons-client`

### Research & Literature
`arxiv-database` `biorxiv-database` `openalex-database` `bgpt-paper-search`
`literature-review` `citation-management` `pyzotero` `perplexity-search`
`research-lookup` `peer-review`

### Biomedical & Clinical
`pyhealth` `clinical-decision-support` `clinical-reports` `treatment-plans`
`clinicaltrials-database` `fda-database` `iso-13485-certification`
`opentargets-database` `primekg` `molecular-dynamics` `fluidsim` `pymatgen`
`pyopenms` `pymoo` `bioservices` `geniml` `etetoolkit` `phylogenetics`

### Economic & Financial Data
`fred-economic-data` `edgartools` `alpha-vantage` `usfiscaldata` `hedgefundmonitor`
`market-research-reports` `uspto-database` `research-grants`

### Document & Output Generation
`pdf` `docx` `xlsx` `pptx` `pptx-posters` `latex-posters` `infographics`
`scientific-schematics` `scientific-slides` `scientific-visualization`
`markdown-mermaid-writing` `paper-2-web` `venue-templates` `generate-image`

### Research Methodology
`hypothesis-generation` `scientific-brainstorming` `scientific-critical-thinking`
`scientific-writing` `scholar-evaluation` `open-notebook` `denario`

### Scientific Computing & Utilities
`zarr-python` `simpy` `parallel-web` `offer-k-dense-web` `get-available-resources`
`markitdown` `what-if-oracle` `consciousness-council` `hypogenic` `matlab`

> Note: If the requested tool is not listed in any category above, do not guess a path. State that the skill is not indexed and suggest checking a related parent library instead.
