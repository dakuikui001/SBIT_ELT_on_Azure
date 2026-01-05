# SBIT Project - Data Schema Documentation

## Table of Contents

### Index

1. [Bronze Layer Tables](#bronze-layer-tables)
   - [registered_users_bz](#registered_users_bz)
   - [gym_logins_bz](#gym_logins_bz)
   - [kafka_multiplex_bz](#kafka_multiplex_bz)

2. [Silver Layer Tables](#silver-layer-tables)
   - [users](#users)
   - [gym_logs](#gym_logs)
   - [user_profile](#user_profile)
   - [heart_rate](#heart_rate)
   - [workouts](#workouts)
   - [user_bins](#user_bins)
   - [completed_workouts](#completed_workouts)
   - [workout_bpm](#workout_bpm)
   - [date_lookup](#date_lookup)

3. [Gold Layer Tables](#gold-layer-tables)
   - [workout_bpm_summary](#workout_bpm_summary)
   - [gym_summary](#gym_summary)

4. [Data Quality Tables](#data-quality-tables)
   - [data_quality_quarantine](#data_quality_quarantine)

---

## Bronze Layer Tables

**Catalog**: `sbit_{env}_catalog` (where env = dev, uat, or prod)  
**Database**: `sbit_db`  
**Purpose**: Raw data ingestion with schema validation and data quality checks  
**Storage**: Delta tables in Unity Catalog  
**Naming Convention**: Tables end with `_bz` suffix

### registered_users_bz

**Description**: Raw user registration data ingested from CSV files via Azure Data Factory. Contains initial user registration information including device identifiers and registration timestamps.

**Source**: CSV files from GitHub (`1-registered_users_*.csv`) processed by ADF pipeline `mainpipelineForCSV`

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | Unique identifier for the user |
| device_id | STRING | NOT NULL | Unique identifier for the user's device |
| mac_address | STRING | NOT NULL | MAC address of the device, used for device identification |
| registration_timestamp | DOUBLE | NULL | Unix timestamp (seconds since epoch) of user registration |
| load_time | TIMESTAMP | NULL | Timestamp when the record was loaded into the bronze layer |
| source_file | STRING | NULL | Path to the source file from which this record was ingested |

**Validation Rules**:
- Non-null constraints: `user_id`, `device_id`, `mac_address`
- Schema validation enforced at ingestion

**Partitioning**: None

---

### gym_logins_bz

**Description**: Raw gym login/logout event data ingested from CSV files. Tracks when users enter and exit gym facilities.

**Source**: CSV files from GitHub (`5-gym_logins_*.csv`) processed by ADF pipeline `mainpipelineForCSV`

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| mac_address | STRING | NOT NULL | MAC address of the device, used to identify the user |
| gym | BIGINT | NOT NULL | Gym facility identifier |
| login | DOUBLE | NULL | Unix timestamp (seconds since epoch) of gym entry |
| logout | DOUBLE | NULL | Unix timestamp (seconds since epoch) of gym exit |
| load_time | TIMESTAMP | NULL | Timestamp when the record was loaded into the bronze layer |
| source_file | STRING | NULL | Path to the source file from which this record was ingested |

**Validation Rules**:
- Non-null constraints: `mac_address`, `gym`
- Timestamp range validation: `login` and `logout` must be between 1577836800 (2020-01-01) and 1893456000 (2030-01-01)

**Partitioning**: None

---

### kafka_multiplex_bz

**Description**: Unified Kafka message stream containing all JSON-based data from Kafka topics (user_info, bpm, workout). Messages are enriched with Kafka metadata and partitioned for efficient querying.

**Source**: Kafka consumer output from Azure Functions writing to ADLS Gen2 `sbit-project/data_zone/raw/kafka_multiplex_bz/`

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| key | STRING | NOT NULL | Kafka message key (typically device_id or user_id) |
| value | STRING | NOT NULL | Kafka message value (JSON payload) |
| topic | STRING | NOT NULL | Kafka topic name (must be one of: "user_info", "bpm", "workout") |
| partition | BIGINT | NULL | Kafka partition number |
| offset | BIGINT | NULL | Kafka message offset within the partition |
| timestamp | TIMESTAMP | NULL | Kafka message timestamp |
| date | DATE | NULL | Date derived from timestamp for partitioning |
| week_part | STRING | NULL | Week identifier in format "YYYY-WW" (e.g., "2024-15") |
| load_time | TIMESTAMP | NULL | Timestamp when the record was loaded into the bronze layer |
| source_file | STRING | NULL | Path to the source file from which this record was ingested |

**Validation Rules**:
- Non-null constraints: `key`, `value`, `topic`
- Topic values must be in set: `["user_info", "bpm", "workout"]`
- Schema validation enforced at ingestion

**Partitioning**: Partitioned by `topic` and `week_part`

---

## Silver Layer Tables

**Catalog**: `sbit_{env}_catalog`  
**Database**: `sbit_db`  
**Purpose**: Cleaned and enriched data with business logic applied, deduplication, and data enrichment  
**Storage**: Delta tables in Unity Catalog  
**Upsert Strategies**: Various (idempotent insert, conditional update, CDC upsert)

### users

**Description**: Deduplicated user master data dimension table. Contains unique user records extracted from registered users bronze table.

**Source**: `registered_users_bz` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | Unique identifier for the user (Primary Key) |
| device_id | STRING | NULL | Unique identifier for the user's device |
| mac_address | STRING | NULL | MAC address of the device |
| registration_timestamp | TIMESTAMP | NULL | User registration timestamp (converted from double) |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Deduplication**: Based on `user_id` and `device_id` combination

---

### gym_logs

**Description**: Gym visit logs with login and logout timestamps. Supports conditional updates when newer logout information is available.

**Source**: `gym_logins_bz` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| mac_address | STRING | NOT NULL | MAC address of the device (Part of Composite Key) |
| gym | BIGINT | NOT NULL | Gym facility identifier (Part of Composite Key) |
| login | TIMESTAMP | NOT NULL | Gym entry timestamp (Part of Composite Key) |
| logout | TIMESTAMP | NULL | Gym exit timestamp, updated if newer logout time is available |

**Upsert Strategy**: Conditional Update (MERGE with WHEN MATCHED AND newer logout THEN UPDATE)

**Deduplication**: Based on `mac_address`, `gym`, and `login` combination

---

### user_profile

**Description**: User profile information with Change Data Capture (CDC) handling. Implements Slowly Changing Dimension (SCD) Type 1 where the latest record wins based on timestamp.

**Source**: `kafka_multiplex_bz` filtered by `topic = 'user_info'` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | Unique identifier for the user (Primary Key) |
| dob | DATE | NULL | Date of birth |
| sex | STRING | NULL | Biological sex |
| gender | STRING | NULL | Gender identity |
| first_name | STRING | NULL | User's first name |
| last_name | STRING | NULL | User's last name |
| street_address | STRING | NULL | Street address component |
| city | STRING | NULL | City name |
| state | STRING | NULL | State or province code |
| zip | INT | NULL | ZIP or postal code |
| updated | TIMESTAMP | NULL | Timestamp when this profile record was last updated |

**Upsert Strategy**: CDC Upsert (MERGE with WHEN MATCHED AND newer updated timestamp THEN UPDATE)

**CDC Processing**: Only processes records with `update_type` in `["new", "update"]`, keeping the latest record per `user_id` based on `updated` timestamp

---

### heart_rate

**Description**: Heart rate (BPM - Beats Per Minute) measurements from devices. Includes validation flag to filter out invalid readings.

**Source**: `kafka_multiplex_bz` filtered by `topic = 'bpm'` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| device_id | STRING | NOT NULL | Device identifier (Part of Composite Key) |
| time | TIMESTAMP | NOT NULL | Timestamp of the heart rate measurement (Part of Composite Key) |
| heartrate | DOUBLE | NULL | Heart rate value in beats per minute |
| valid | BOOLEAN | NULL | Validation flag: `true` if heartrate > 0, `false` otherwise |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Deduplication**: Based on `device_id` and `time` combination

**Validation**: Records with `heartrate <= 0` are marked as `valid = false`

---

### workouts

**Description**: Workout start/stop events from user devices. Tracks individual workout sessions with action types.

**Source**: `kafka_multiplex_bz` filtered by `topic = 'workout'` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | User identifier (Part of Composite Key) |
| workout_id | STRING | NULL | Unique identifier for the workout |
| time | TIMESTAMP | NOT NULL | Timestamp of the workout event (Part of Composite Key) |
| action | STRING | NULL | Action type: "start" or "stop" |
| session_id | STRING | NULL | Session identifier to group related workout events |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Deduplication**: Based on `user_id` and `time` combination

---

### user_bins

**Description**: User demographic bins derived from user profile data. Contains age groups, gender, and location information for analytics and segmentation.

**Source**: Derived from `user_profile` joined with `users` (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | Unique identifier for the user (Primary Key) |
| age | STRING | NULL | Age bin category: "under 18", "18-25", "25-35", "35-45", "45-55", "55-65", "65-75", "75-85", "85-95", "95+", or "invalid age" |
| gender | STRING | NULL | Gender identity from user profile |
| city | STRING | NULL | City name from user profile |
| state | STRING | NULL | State or province code from user profile |

**Upsert Strategy**: SCD Type 1 (MERGE with WHEN MATCHED THEN UPDATE, WHEN NOT MATCHED THEN INSERT)

**Age Binning Logic**: Calculated from date of birth using floor(months_between(current_date, dob) / 12)

---

### completed_workouts

**Description**: Matched workout sessions created by joining workout start and stop events within a 3-hour window. Represents completed workout sessions.

**Source**: Derived from `workouts` table by matching start/stop events (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | User identifier (Part of Composite Key) |
| workout_id | STRING | NOT NULL | Workout identifier (Part of Composite Key) |
| session_id | STRING | NOT NULL | Session identifier (Part of Composite Key) |
| start_time | TIMESTAMP | NULL | Workout start timestamp |
| end_time | TIMESTAMP | NULL | Workout end timestamp |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Matching Logic**: 
- Joins workout events with `action = 'start'` and `action = 'stop'`
- Matches on `user_id`, `workout_id`, and `session_id`
- Stop event must occur within 3 hours of start event
- State cleanup configured for 3-hour windows

---

### workout_bpm

**Description**: Workout sessions enriched with heart rate data using temporal joins. Associates heart rate measurements with workout sessions.

**Source**: Derived from `completed_workouts` and `heart_rate` tables using temporal join (Silver layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| user_id | STRING | NOT NULL | User identifier (Part of Composite Key) |
| workout_id | STRING | NOT NULL | Workout identifier (Part of Composite Key) |
| session_id | STRING | NOT NULL | Session identifier (Part of Composite Key) |
| start_time | TIMESTAMP | NULL | Workout start timestamp |
| end_time | TIMESTAMP | NULL | Workout end timestamp |
| time | TIMESTAMP | NOT NULL | Heart rate measurement timestamp (Part of Composite Key) |
| heartrate | DOUBLE | NULL | Heart rate value in beats per minute at the given time |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Temporal Join Logic**:
- Joins `completed_workouts` with `heart_rate` on `device_id`
- Heart rate measurement must occur between `start_time` and `end_time`
- Workout must end within 3 hours of heart rate measurement
- Only includes valid heart rate records (`valid = True`)
- State cleanup configured for 3-hour windows

---

### date_lookup

**Description**: Date dimension table for calendar lookups. Contains date attributes and week partitions for time-based analytics.

**Source**: Generated data covering date range from 2020-01-01 to 2030-12-31 (History loader)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| date | DATE | NOT NULL | Calendar date (Primary Key) |
| week | INT | NULL | Week number of the year (1-53) |
| year | INT | NULL | Year (e.g., 2024) |
| month | INT | NULL | Month number (1-12) |
| dayofweek | INT | NULL | Day of week (1=Sunday, 7=Saturday) |
| dayofmonth | INT | NULL | Day of month (1-31) |
| dayofyear | INT | NULL | Day of year (1-366) |
| week_part | STRING | NULL | Week identifier in format "YYYY-WW" (e.g., "2024-15") |

**Default Date Range**: 2020-01-01 to 2030-12-31 (4,018 days)

---

## Gold Layer Tables

**Catalog**: `sbit_{env}_catalog`  
**Database**: `sbit_db`  
**Purpose**: Business-ready aggregated tables for reporting and analytics  
**Storage**: Delta tables in Unity Catalog  
**Naming Convention**: Tables end with `_summary` suffix

### workout_bpm_summary

**Description**: Aggregated workout heart rate metrics by user demographics. Provides summary statistics (min/avg/max BPM) per workout session with user demographic information.

**Source**: Aggregated from `workout_bpm` joined with `user_bins` (Gold layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| workout_id | STRING | NOT NULL | Workout identifier (Part of Composite Key) |
| session_id | STRING | NOT NULL | Session identifier (Part of Composite Key) |
| user_id | STRING | NOT NULL | User identifier (Part of Composite Key) |
| age | STRING | NULL | Age bin category from user_bins |
| gender | STRING | NULL | Gender from user_bins |
| city | STRING | NULL | City from user_bins |
| state | STRING | NULL | State from user_bins |
| min_bpm | DOUBLE | NULL | Minimum heart rate during the workout session |
| avg_bpm | DOUBLE | NULL | Average heart rate during the workout session |
| max_bpm | DOUBLE | NULL | Maximum heart rate during the workout session |
| num_recordings | BIGINT | NULL | Number of heart rate recordings in the workout session |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Aggregation Logic**:
- Groups by `user_id`, `workout_id`, `session_id`, and `end_time`
- Calculates min, mean (avg), max, and count of heartrate values
- Joins with `user_bins` to enrich with demographic information

---

### gym_summary

**Description**: Gym visit summaries with time spent in gym versus time exercising. Combines gym login/logout data with workout session data.

**Source**: Derived from `gym_logs` and `completed_workouts` joined with `users` (Gold layer transformation)

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| date | DATE | NULL | Date of the gym visit (derived from login timestamp) |
| gym | BIGINT | NULL | Gym facility identifier |
| mac_address | STRING | NULL | MAC address of the device |
| workout_id | STRING | NOT NULL | Workout identifier (Part of Composite Key) |
| session_id | STRING | NOT NULL | Session identifier (Part of Composite Key) |
| minutes_in_gym | DOUBLE | NULL | Total minutes spent in the gym (calculated as (logout - login) / 60) |
| minutes_exercising | DOUBLE | NULL | Total minutes spent exercising (calculated as (end_time - start_time) / 60) |

**Upsert Strategy**: Idempotent Insert (MERGE with WHEN NOT MATCHED THEN INSERT)

**Join Logic**:
- Joins `gym_logs` with `completed_workouts` via `users` table (using `mac_address` and `user_id`)
- Workout must occur between gym login and logout times
- Calculates time differences in minutes

**Note**: This table is created using `CREATE OR REPLACE TABLE AS SELECT` in the setup, but uses streaming upsert in the gold layer processing.

---

## Data Quality Tables

**Catalog**: `sbit_{env}_catalog`  
**Database**: `gx` (Great Expectations database)  
**Purpose**: Store records that failed data quality validation

### data_quality_quarantine

**Description**: Universal data quality quarantine table for storing records that failed Great Expectations (GX) validation. Records are quarantined at the bronze layer ingestion stage.

**Source**: Records that fail GX validation during bronze layer ingestion

| Column Name | Data Type | Nullable | Description |
|------------|-----------|----------|-------------|
| table_name | STRING | NULL | The name of the source table where the data originated (e.g., "kafka_multiplex_bz", "registered_users_bz", "gym_logins_bz") |
| gx_batch_id | STRING | NULL | The identifier for the GX validation run (casted to string). Used for traceability and batch tracking |
| violated_rules | STRING | NULL | A list or description of the rules that failed validation. Can be "Table-level Schema/Count Error" or specific column-level rule violations |
| raw_data | STRING | NULL | The original record stored in JSON format. Preserves the complete record for investigation and potential reprocessing |
| ingestion_time | TIMESTAMP | NULL | The timestamp when the record was quarantined |

**Storage Location**: `{project_dir}gx/data_quality_quarantine/`

**Table Properties**:
- `delta.columnMapping.mode` = 'name'
- `delta.minReaderVersion` = '2'
- `delta.minWriterVersion` = '5'

**Validation Behavior**:
- **Row-level failures**: Only failed rows are quarantined, valid rows proceed to target table
- **Table-level failures**: Entire batch is quarantined if schema/structure errors occur
- **Validation success**: All data proceeds to target table

---

## Schema Relationships

### Data Flow Summary

```
Bronze Layer (Raw Data)
├── registered_users_bz → Silver: users
├── gym_logins_bz → Silver: gym_logs
└── kafka_multiplex_bz → Silver: user_profile, heart_rate, workouts
    │
    ├── topic='user_info' → user_profile → user_bins
    ├── topic='bpm' → heart_rate
    └── topic='workout' → workouts → completed_workouts
        │
        └── completed_workouts + heart_rate → workout_bpm
            │
            └── workout_bpm + user_bins → Gold: workout_bpm_summary

gym_logs + completed_workouts + users → Gold: gym_summary
```

### Key Relationships

1. **users** ← `registered_users_bz` (1:1 deduplication)
2. **gym_logs** ← `gym_logins_bz` (1:1 with conditional updates)
3. **user_profile** ← `kafka_multiplex_bz` (CDC, 1:many with latest wins)
4. **heart_rate** ← `kafka_multiplex_bz` (1:1 idempotent)
5. **workouts** ← `kafka_multiplex_bz` (1:1 idempotent)
6. **user_bins** ← `user_profile` + `users` (derived dimension)
7. **completed_workouts** ← `workouts` (temporal join of start/stop events)
8. **workout_bpm** ← `completed_workouts` + `heart_rate` (temporal join)
9. **workout_bpm_summary** ← `workout_bpm` + `user_bins` (aggregation)
10. **gym_summary** ← `gym_logs` + `completed_workouts` + `users` (join and aggregation)

---

## Environment Configuration

All tables are created in environment-specific catalogs:
- **Development**: `sbit_dev_catalog.sbit_db.*`
- **UAT**: `sbit_uat_catalog.sbit_db.*`
- **Production**: `sbit_prod_catalog.sbit_db.*`

The data quality quarantine table is in a separate database:
- `sbit_{env}_catalog.gx.data_quality_quarantine`

---

## Notes

- All tables use **Delta Lake** format for ACID transactions and time travel capabilities
- Tables are managed by **Unity Catalog** for data governance and access control
- Streaming jobs use **checkpointing** for fault tolerance
- **Watermarking** is enabled for late data handling (30-second windows)
- **State cleanup** is configured for temporal joins (3-hour windows)
- Delta table optimization is enabled (auto-compact, optimized writes)
- All timestamps in Bronze layer are stored as DOUBLE (Unix timestamps) and converted to TIMESTAMP in Silver layer

---

**Document Version**: 1.0    
**Project**: SBIT - Azure Data Platform

