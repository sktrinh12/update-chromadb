# Azure DevOps → ChromaDB Sync Pipeline

This repository contains a GitHub Actions workflow that builds and publishes a complete semantic-search index of Azure DevOps work items. The resulting ChromaDB dataset is stored in S3 and later consumed by a ChromaDB server running in EKS.

## Overview

Each workflow run performs a **full rebuild** of the work-item knowledge base:

1. **Assume AWS IAM Role**
   The workflow authenticates to AWS using OIDC and assumes a role with permission to write to a dedicated S3 bucket.

2. **Fetch all Azure DevOps Work Items**
   Runs `fetch_workitems.py`, which queries the Azure DevOps REST API for **all** work items in the project and all associated comments.

3. **Clean & Normalize the Data**
   Runs `clean_workitems.py` to:

   * Strip HTML, formatting artifacts, and non-useful noise
   * Normalize fields (title, description, comments, authors, dates, tags)
   * Produce structured records optimized for vector embeddings

4. **Upload to S3 (Overwrite Existing Dataset)**
   The entire `./chroma` directory is synced to an S3 path such as:
   This ensures the latest index is always available for downstream services.

## EKS ChromaDB Server Integration

An EKS workload (Deployment + EBS volume) hosts the production ChromaDB server.
After this workflow publishes new data, the EKS cluster can run a **Kubernetes Job** that:

* Downloads the S3 `/chroma` directory
* Overwrites the EBS-mounted `./chroma` folder inside the pod
* Restarts the server or signals it to reload the data

This keeps the ChromaDB server always in sync with Azure DevOps work items.

## Why Full Rebuilds?

Rather than doing incremental syncs, this workflow always fetches the entire dataset.
This avoids:

* Missed edits
* Out-of-order comments
* Partial updates
* Date-filtering issues
* Drift between Azure DevOps and ChromaDB

The pipeline is simple, deterministic, and always produces a consistent index.
