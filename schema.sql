-- ============================================================================
-- Call Analysis System - MySQL Schema
-- ============================================================================

-- Table: call_records
-- Stores all Zoom Phone call data with transcription and analysis results
-- ============================================================================

CREATE TABLE IF NOT EXISTS call_records (
    -- Primary key
    id                      VARCHAR(36) PRIMARY KEY,
    
    -- Call identification (from Zoom)
    call_id                 VARCHAR(100) UNIQUE NOT NULL,
    
    -- Agent information
    agent_id                VARCHAR(36),
    agent_name              VARCHAR(120),
    
    -- Customer information
    customer_number         VARCHAR(50),
    
    -- Call timing
    start_time              DATETIME,
    end_time                DATETIME,
    duration_seconds        INT,
    
    -- Recording source
    recording_url           TEXT,
    recording_file_type     VARCHAR(20),
    
    -- -------------------------------------------------------------------------
    -- Transcription fields
    -- -------------------------------------------------------------------------
    transcript_text         LONGTEXT,
    language_detected       VARCHAR(10),
    transcription_status    ENUM('pending', 'processing', 'success', 'failed') DEFAULT 'pending',
    transcription_error     TEXT,
    transcription_started_at DATETIME,
    transcription_completed_at DATETIME,
    
    -- -------------------------------------------------------------------------
    -- AI Analysis fields
    -- -------------------------------------------------------------------------
    overall_score           TINYINT UNSIGNED,                -- 1-5
    has_warning             BOOLEAN DEFAULT FALSE,
    warning_reasons_json    JSON,                            -- Array of warning tags
    short_summary           TEXT,                            -- English summary
    customer_sentiment      ENUM('positive', 'neutral', 'negative'),
    department              VARCHAR(50),
    
    analysis_status         ENUM('pending', 'processing', 'success', 'failed') DEFAULT 'pending',
    analysis_error          TEXT,
    analysis_started_at     DATETIME,
    analysis_completed_at   DATETIME,
    
    -- -------------------------------------------------------------------------
    -- Email alert fields
    -- -------------------------------------------------------------------------
    alert_email_status      ENUM('pending', 'sent', 'failed', 'not_needed') DEFAULT 'pending',
    alert_sent_at           DATETIME,
    alert_email_error       TEXT,
    
    -- -------------------------------------------------------------------------
    -- Metadata
    -- -------------------------------------------------------------------------
    retry_count             INT DEFAULT 0,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- -------------------------------------------------------------------------
    -- Indexes for worker queries
    -- -------------------------------------------------------------------------
    INDEX idx_call_id (call_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_transcription_status (transcription_status),
    INDEX idx_analysis_status (analysis_status),
    INDEX idx_alert_status (alert_email_status, has_warning),
    INDEX idx_pending_transcription (transcription_status, created_at),
    INDEX idx_pending_analysis (analysis_status, transcription_status),
    INDEX idx_pending_alerts (alert_email_status, has_warning, analysis_status),
    INDEX idx_created_at (created_at)
    
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Worker status tracking (optional - for monitoring)
-- ============================================================================

CREATE TABLE IF NOT EXISTS worker_status (
    id                      VARCHAR(36) PRIMARY KEY,
    worker_type             ENUM('transcription', 'analysis', 'alert') NOT NULL,
    last_heartbeat          DATETIME,
    jobs_processed          INT DEFAULT 0,
    jobs_failed             INT DEFAULT 0,
    status                  ENUM('running', 'stopped', 'error') DEFAULT 'stopped',
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY unique_worker (worker_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
