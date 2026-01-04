# SBIT Project - Azure Data Platform

A modern data engineering platform implementing a medallion architecture on Azure, processing fitness and user data with real-time streaming capabilities, data quality validation, and automated ETL pipelines.

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [Components](#components)
   - [Azure Functions](#azure-functions)
   - [Azure Data Factory](#azure-data-factory)
   - [Azure Databricks](#azure-databricks)
   - [Data Quality](#data-quality)
5. [Data Layers](#data-layers)
   - [Bronze Layer](#bronze-layer)
   - [Silver Layer](#silver-layer)
   - [Gold Layer](#gold-layer)
6. [Reports](#reports)

---

## Project Overview

This project implements an end-to-end data pipeline for processing fitness data including user registrations, gym logins, heart rate (BPM) measurements, workout sessions, and user profile information. The architecture follows a medallion (Bronze-Silver-Gold) pattern with real-time streaming, data quality validation, and automated orchestration.

**Key Features:**
- Real-time data ingestion via Kafka
- Automated ETL pipelines using Azure Data Factory
- Stream processing with Databricks Structured Streaming
- Data quality validation using Great Expectations
- Medallion architecture with incremental processing
- Multi-environment support (dev, uat, prod)

---

## Architecture

![Project Architecture](Project%20Architechture.png)

---

## Data Flow

### 1. **Data Ingestion Layer**

#### CSV Files (Batch Processing)
- **Source**: GitHub repository
- **Azure Data Factory Pipeline**: `mainpipelineForCSV`
  - Reads CSV files from GitHub (registered users, gym logins)
  - Copies to ADLS Gen2: `sbit-project/data_zone/input/`
- **Files Processed**:
  - `1-registered_users_*.csv`
  - `5-gym_logins_*.csv`

#### JSON Files (Streaming via Kafka)
- **Source**: GitHub repository
- **Azure Data Factory Pipeline**: `mainpipelineForJson`
  - Reads JSON files from GitHub (user info, BPM, workout)
  - Copies to ADLS Gen2: `sbit-project/data_zone/input/`
- **Files Processed**:
  - `2-user_info_*.json`
  - `3-bpm_*.json`
  - `4-workout_*.json`

### 2. **Kafka Integration Layer**

#### Producers (Azure Functions)
Three Azure Functions monitor ADLS Gen2 `input/` folder and publish to Kafka topics:

| Function | Kafka Topic | File Pattern | Consumer Group |
|----------|-------------|--------------|----------------|
| `SBIT_bmp_azure_function` | `bpm` | `3-bpm_*.json` | `consumer_group4` |
| `SBIT_user_info_azure_function` | `user_info` | `2-user_info_*.json` | `consumer_group4` |
| `SBIT_workout_azure_function` | `workout` | `4-workout_*.json` | `consumer_group4` |

**Producer Flow:**
1. Blob trigger detects new files in `sbit-project/data_zone/input/`
2. Function reads and parses JSON files
3. Messages published to Confluent Kafka with SASL_SSL authentication
4. Key-value pairs: `device_id`/`user_id` as key, JSON payload as value

#### Consumers (Azure Functions)
Three Azure Functions consume from Kafka topics and write to ADLS:

**Consumer Flow:**
1. Kafka trigger receives messages from topics (`bpm`, `user_info`, `workout`)
2. Messages are enriched with Kafka metadata (topic, partition, offset, timestamp)
3. Batched and written to ADLS Gen2: `sbit-project/data_zone/raw/kafka_multiplex_bz/`
4. Format: JSON with columns `key`, `value`, `topic`, `partition`, `offset`, `timestamp`

### 3. **Data Processing Layer (Databricks)**

#### Bronze Layer - Raw Data Ingestion
**Purpose**: Ingest raw data with schema validation and data quality checks

**Sources:**
- CSV files: `registered_users_bz`, `gym_logins_bz` (from `input/` via ADF)
- Kafka multiplex: `kafka_multiplex_bz` (from Kafka consumers)

**Processing:**
- Streams data using `cloudFiles` source
- Adds metadata: `load_time`, `source_file`
- Applies Great Expectations validation at ingestion
- Quarantines invalid records to `data_quality_quarantine` table
- Writes validated data to Delta tables with checkpointing

**Tables:**
- `registered_users_bz`: User registration data
- `gym_logins_bz`: Gym login/logout events
- `kafka_multiplex_bz`: Unified Kafka message stream (partitioned by `topic`, `week_part`)

#### Silver Layer - Cleaned and Enriched Data
**Purpose**: Apply business logic, deduplication, and data enrichment

**Phase 1: Core Fact/Dimension Tables**
- `users`: Deduplicated user master data (from `registered_users_bz`)
- `gym_logs`: Gym session logs with conditional updates (from `gym_logins_bz`)
- `user_profile`: CDC-based user profile with SCD Type 1 (from `kafka_multiplex_bz` topic `user_info`)
- `heart_rate`: Heart rate measurements (from `kafka_multiplex_bz` topic `bpm`)
- `workouts`: Workout start/stop events (from `kafka_multiplex_bz` topic `workout`)

**Phase 2: Derived Dimensions and Matching**
- `user_bins`: Age, gender, location demographics (derived from `user_profile`)
- `completed_workouts`: Matched workout sessions (join start/stop events within 3 hours)

**Phase 3: Enriched Fact Tables**
- `workout_bpm`: Workout sessions enriched with heart rate data (temporal join)

**Upsert Strategies:**
- **Idempotent Insert**: `users`, `heart_rate`, `workouts` (MERGE with NOT MATCHED)
- **Conditional Update**: `gym_logs` (updates logout if newer)
- **CDC Upsert**: `user_profile` (latest record wins based on timestamp)

#### Gold Layer - Aggregated Analytics
**Purpose**: Business-ready aggregated tables for reporting

**Tables:**
- `workout_bpm_summary`: Aggregated workout heart rate metrics (min/avg/max BPM) by user demographics
- `gym_summary`: Gym visit summaries with time spent in gym vs. exercising

**Aggregations:**
- Heart rate statistics per workout session
- Gym utilization metrics
- User demographic segmentation

### 4. **Data Quality Validation**

**Framework**: Great Expectations (GX) 1.10.0

**Validation Points:**
- **Bronze Layer**: All incoming data validated before ingestion
- **Validation Method**: Batch-level validation using GX Validation Definitions
- **Quarantine**: Invalid records stored in `sbit_dev_catalog.gx.data_quality_quarantine`

**Validation Rules:**

| Table | Validation Rules |
|-------|-----------------|
| `kafka_multiplex_bz` | - Column schema match<br>- Non-null: key, value, topic<br>- Topic values in: `["user_info", "bpm", "workout"]` |
| `registered_users_bz` | - Column schema match<br>- Non-null: user_id, device_id, mac_address |
| `gym_logins_bz` | - Column schema match<br>- Non-null: mac_address, gym<br>- Timestamp range validation (login, logout) |

**Quarantine Table Schema:**
```sql
- table_name: Source table name
- gx_batch_id: Validation batch identifier
- violated_rules: Description of failed rules
- raw_data: Original record in JSON format
- ingestion_time: Quarantine timestamp
```

**Processing Behavior:**
- **Row-level failures**: Only failed rows quarantined, valid rows proceed
- **Table-level failures**: Entire batch quarantined if schema/structure errors
- **Validation success**: All data proceeds to target table

---

## Components

### Azure Functions

**Location**: `SBIT_*/`

**Three Function Apps:**
1. **SBIT_bmp_azure_function**: Heart rate data processing
2. **SBIT_user_info_azure_function**: User profile data processing
3. **SBIT_workout_azure_function**: Workout session data processing

**Each Function App Contains:**
- **Producer**: Blob-triggered function publishing to Kafka
- **Consumer**: Kafka-triggered function writing to ADLS

**Configuration**:
- Environment variables: `KafkaConnString`, `KafkaUsername`, `KafkaPassword`
- Storage connection: `STORAGE_ACCOUNT_CONNECTION`
- Kafka protocol: SASL_SSL with PLAIN authentication

### Azure Data Factory

**Location**: `data_factory_SBIT/`

**Pipelines:**
- **Mainpipeline**: Orchestrates CSV and JSON pipelines sequentially
- **mainpipelineForCSV**: Processes CSV files from GitHub to ADLS
- **mainpipelineForJson**: Processes JSON files from GitHub to ADLS
- **subpipelineForCSV**: Sub-pipeline for CSV file iteration
- **subpipelineForJson**: Sub-pipeline for JSON file iteration

**Linked Services:**
- `from_github_linked_service`: GitHub connection
- `to_gen2_linked_service`: ADLS Gen2 connection

**Datasets:**
- `csvFromGithub`, `csvToGen2`: CSV file datasets
- `JsonFromGithub`, `JsonToGen2`: JSON file datasets

### Azure Databricks

**Location**: `databricks_SBIT/`

**Notebooks:**
- `00_main.ipynb`: Setup and history loading (initialization)
- `01_config.ipynb`: Configuration class with paths and settings
- `02_setup.ipynb`: Database and table creation
- `03_history_loader.ipynb`: Historical data loading
- `04_bronze.ipynb`: Bronze layer ingestion with GX validation
- `05_silver.ipynb`: Silver layer transformations and upserts
- `06_gold.ipynb`: Gold layer aggregations
- `07_run.ipynb`: Main execution notebook (supports batch/streaming)
- `great_expectations_common.py`: GX validation utilities
- `great_expectations_setting.ipynb`: GX suite configuration

**Execution Modes:**
- **Batch Mode**: `RunType="once"` - Processes available data and stops
- **Streaming Mode**: `RunType="continuous"` - Continuous micro-batch processing

**Environments**: Supports `dev`, `uat`, `prod` via catalog naming

### Data Quality

**Implementation**: `great_expectations_common.py`

**Key Features:**
- Thread-safe GX context management
- Suite preloading for performance
- Row-level and table-level validation
- Automatic quarantine of failed records
- Batch ID tracking for traceability

**Validation Flow:**
1. Micro-batch arrives at Bronze layer
2. Assign monotonically increasing ID to each row
3. Load GX suite for target table
4. Execute validation definition
5. If successful → write to target table
6. If failed → quarantine failed rows, write valid rows

---

## Data Layers

### Bronze Layer

**Storage**: Delta tables in Unity Catalog
**Location**: `sbit_{env}_catalog.sbit_db.*_bz`

**Tables:**
- `registered_users_bz`: User registration raw data
- `gym_logins_bz`: Gym login raw data  
- `kafka_multiplex_bz`: Unified Kafka stream (partitioned by topic, week_part)

**Characteristics:**
- Schema enforced at ingestion
- Data quality validation with Great Expectations
- Metadata tracking (load_time, source_file)
- Checkpoint-based streaming recovery

### Silver Layer

**Storage**: Delta tables in Unity Catalog
**Location**: `sbit_{env}_catalog.sbit_db.*`

**Core Tables:**
- `users`: Master user dimension
- `user_profile`: User profile with CDC handling
- `gym_logs`: Gym visit logs
- `heart_rate`: Heart rate measurements
- `workouts`: Workout events

**Derived Tables:**
- `user_bins`: User demographic bins (age, gender, location)
- `completed_workouts`: Matched workout sessions
- `workout_bpm`: Workouts enriched with heart rate

**Characteristics:**
- Business logic applied
- Deduplication and watermarking
- CDC processing for slowly changing dimensions
- Temporal joins for event correlation
- MERGE-based upserts for idempotency

### Gold Layer

**Storage**: Delta tables in Unity Catalog
**Location**: `sbit_{env}_catalog.sbit_db.*_summary`

**Tables:**
- `workout_bpm_summary`: Aggregated workout heart rate analytics
- `gym_summary`: Gym utilization summaries

**Characteristics:**
- Aggregated metrics (min/avg/max, counts)
- Joined with dimension data
- Ready for business intelligence consumption
- Idempotent inserts only

---

## Reports

**Location**: `report/`

**Power BI Report**: `SBIT_analysis_report.pbix`

**Sample Dashboard**:
![Dashboard Sample](report/sample/dashboard.png)

The Power BI report connects to Gold layer tables for visualization and analysis of:
- Workout performance metrics
- Gym utilization statistics
- User demographic analysis
- Heart rate trends

---

## Project Structure

```
Azure_git/
├── adls/                          # ADLS Gen2 structure
│   └── sbit_project/
│       ├── checkpoints/           # Stream processing checkpoints
│       ├── data_zone/
│       │   ├── input/             # ADF output (from GitHub)
│       │   └── raw/               # Kafka consumer output
│       └── gx/                    # Great Expectations
│           ├── data_quality_quarantine/  # Quarantined records
│           └── gx_configs/        # GX suite configurations
├── data_factory_SBIT/             # Azure Data Factory pipelines
├── databricks_SBIT/               # Databricks notebooks
├── SBIT_bmp_azure_function/       # BPM Kafka producer/consumer
├── SBIT_user_info_azure_function/ # User info Kafka producer/consumer
├── SBIT_workout_azure_function/   # Workout Kafka producer/consumer
└── report/                        # Power BI reports
```

---

## Key Technologies

- **Azure Data Lake Storage Gen2**: Data storage
- **Azure Databricks**: Stream processing and transformations
- **Azure Data Factory**: ETL orchestration
- **Azure Functions**: Event-driven Kafka integration
- **Confluent Kafka**: Message streaming platform
- **Great Expectations**: Data quality validation
- **Delta Lake**: ACID transactions and time travel
- **Unity Catalog**: Data governance and access control
- **Power BI**: Business intelligence and reporting

---

## Environment Configuration

The project supports multiple environments:
- **Development**: `sbit_dev_catalog`
- **UAT**: `sbit_uat_catalog`
- **Production**: `sbit_prod_catalog`

Environment is selected via Databricks widget: `env` parameter (`dev`, `uat`, `prod`)

---

## Data Quality Workflow

1. **Ingestion**: Data arrives at Bronze layer via ADF (CSV) or Kafka consumers (JSON)
2. **Validation**: Great Expectations suite executed per micro-batch
3. **Quarantine**: Failed records → `data_quality_quarantine` table
4. **Proceed**: Valid records → Bronze Delta tables
5. **Transformation**: Silver layer applies business rules
6. **Aggregation**: Gold layer creates analytics-ready summaries

---

## Notes

- All streaming jobs use checkpointing for fault tolerance
- Watermarking enabled for late data handling (30-second windows)
- Micro-batch intervals configurable (default: 5-15 seconds)
- State cleanup configured for temporal joins (3-hour windows)
- Delta table optimization enabled (auto-compact, optimized writes)

