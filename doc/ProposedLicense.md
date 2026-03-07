# Proposed License

## WikiOracle Licensing Architecture

This document proposes a licensing structure for the WikiOracle project
designed to preserve software freedom, maintain an open knowledge
commons, and enable responsible AI development.

### Four-Layer Conceptual Model

WikiOracle separates artifacts into distinct licensing domains.

  Layer      Artifact Type             Recommended License
  ---------- ------------------------- ---------------------
  Layer 1    Software / engine code    GPL-3.0
  Layer 2    Human knowledge content   CC BY-SA 4.0
  Layer 3    Structured data           CC0
  Layer 3B   Model weights             Apache-2.0

Conceptual summary:

    code → algorithms
    data → facts
    weights → learned structure
    content → explanations

This layered separation mirrors successful open knowledge systems while
extending them for AI systems.


## #License Comparison Table

  -------------------------------------------------------------------------
  License      Domain       Key Features            Typical Use
  ------------ ------------ ----------------------- -----------------------
  GPL-3.0      Software     Strong copyleft, patent Infrastructure software
                            protection, source      
                            distribution            
                            requirement             

  CC BY-SA 4.0 Creative     Attribution required,   Wikipedia articles
               works        derivatives must remain 
                            under same license      

  Apache-2.0   Software /   Permissive reuse with   AI models and developer
               model        patent grant            tools
               artifacts                            
  -------------------------------------------------------------------------

### GPL-3.0

Properties:

*   strong copyleft protection
*   requires publication of source code
*   includes explicit patent protection
*   prevents proprietary forks of infrastructure

### CC BY-SA 4.0

Properties:

*   allows copying and adaptation
*   requires attribution
*   derivatives must remain under the same license
*   widely used for collaborative knowledge projects

### Apache-2.0

Properties:

*   permissive reuse
*   explicit patent protection
*   compatible with commercial ecosystems
*   widely used for machine learning artifacts


## Rationale for Layered Licensing

### Software (GPL-3.0)

The WikiOracle engine should remain permanently open. GPL ensures that
improvements to the infrastructure remain open-source and cannot be
captured by proprietary forks.

### Knowledge Content (CC BY-SA)

Human-authored knowledge should remain part of a global commons. CC
BY-SA ensures attribution and share-alike behavior so improvements
remain public.

### Structured Data (CC0)

Structured datasets (truth graphs, semantic relations, dataset exports)
benefit from minimal legal friction. CC0 allows unrestricted reuse and
avoids attribution chains that complicate machine learning workflows.

### Model Weights (Apache-2.0)

Model weights are derived artifacts produced by training. Apache-2.0
allows redistribution, fine-tuning, and commercial use while providing
patent protection.

## Training Data Provenance Policy

AI systems increasingly require transparent documentation of training
sources.

WikiOracle should maintain a provenance record including:

*   dataset origin
*   license compatibility
*   ingestion date
*   preprocessing steps
*   contributor identity (if applicable)

This allows:

*   legal defensibility
*   reproducibility
*   verification of training inputs

Example provenance record structure:

    dataset_name
    source_url
    license
    date_ingested
    transformation_pipeline

Provenance tracking supports both transparency and scientific
reproducibility.

## AI-Generated Content Policy

AI-generated text occupies a hybrid authorship category.

WikiOracle should treat generated content in three stages:

  Stage                      License
  -------------------------- ----------
  Raw AI output              CC0
  AI draft edited by human   CC BY-SA
  Human-authored content     CC BY-SA

Rationale:

*   raw AI output may lack clear authorship
*   human editorial involvement establishes attribution
*   share-alike preserves the knowledge commons

All AI contributions should record metadata:

    generation_model
    timestamp
    human_editor
    revision_history

This ensures transparency regarding machine involvement.

## Summary

WikiOracle licensing stack:

    Layer 1 — Software
    GPL-3.0

    Layer 2 — Knowledge Content
    CC BY-SA 4.0

    Layer 3 — Structured Data
    CC0

    Layer 3B — Model Weights
    Apache-2.0

The architecture protects the software commons, maintains a global
knowledge commons, and supports open AI development.
