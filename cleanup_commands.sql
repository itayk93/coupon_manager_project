-- Database Cleanup Commands
-- Coupon Manager Project - Unused Tables Removal
-- Execute in order, test in development first!

-- =====================================================
-- PHASE 1: REMOVE COMPLETELY UNUSED TABLES (0 rows)
-- =====================================================

-- Remove marketplace tables that are never used
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS user_ratings;
DROP TABLE IF EXISTS coupon_requests;

-- Remove GDPR opt-out table (no users opted out)
DROP TABLE IF EXISTS opt_outs;

-- Remove newsletter sending tracking (no newsletters sent)
DROP TABLE IF EXISTS newsletter_sendings;

-- =====================================================
-- PHASE 2: REMOVE UNUSED COLUMNS (High Priority)
-- =====================================================

-- Remove completely unused user fields
ALTER TABLE users DROP COLUMN IF EXISTS age;

-- Remove unused coupon fields
ALTER TABLE coupon DROP COLUMN IF EXISTS auto_download_details;
ALTER TABLE coupon DROP COLUMN IF EXISTS notification_sent_pagh_tokev;
ALTER TABLE coupon DROP COLUMN IF EXISTS notification_sent_nutzel;

-- Remove underutilized buyme integration field
ALTER TABLE coupon DROP COLUMN IF EXISTS buyme_coupon_url;

-- =====================================================
-- PHASE 3: OPTIONAL OPTIMIZATIONS
-- =====================================================

-- Consider removing if profile features aren't important
-- ALTER TABLE users DROP COLUMN IF EXISTS profile_description;
-- ALTER TABLE users DROP COLUMN IF EXISTS profile_image;

-- Consider simplifying if only one admin message exists
-- DROP TABLE IF EXISTS admin_messages;

-- Consider replacing with config file if only 2 feature flags
-- DROP TABLE IF EXISTS feature_access;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================

-- Check tables that will be removed have 0 rows
SELECT 'transactions' as table_name, COUNT(*) as row_count FROM transactions
UNION ALL
SELECT 'user_ratings', COUNT(*) FROM user_ratings
UNION ALL
SELECT 'coupon_requests', COUNT(*) FROM coupon_requests
UNION ALL
SELECT 'opt_outs', COUNT(*) FROM opt_outs
UNION ALL
SELECT 'newsletter_sendings', COUNT(*) FROM newsletter_sendings;

-- Verify columns exist before dropping
SELECT column_name, table_name 
FROM information_schema.columns 
WHERE table_name IN ('users', 'coupon') 
AND column_name IN ('age', 'auto_download_details', 'notification_sent_pagh_tokev', 'notification_sent_nutzel', 'buyme_coupon_url')
ORDER BY table_name, column_name;

-- =====================================================
-- ESTIMATED STORAGE SAVINGS
-- =====================================================

-- Before cleanup - check current database size
SELECT 
    schemaname,
    tablename,
    attname as column_name,
    n_distinct,
    correlation
FROM pg_stats 
WHERE schemaname = 'public' 
AND tablename IN ('transactions', 'user_ratings', 'coupon_requests', 'opt_outs', 'newsletter_sendings')
ORDER BY tablename;

-- Check total row counts for verification
SELECT 
    table_name,
    (xpath('/row/cnt/text()', xml_count))[1]::text::int as row_count
FROM (
    SELECT 
        table_name, 
        query_to_xml(format('select count(*) as cnt from %I.%I', table_schema, table_name), false, true, '') as xml_count
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name IN ('transactions', 'user_ratings', 'coupon_requests', 'opt_outs', 'newsletter_sendings', 'users', 'coupon')
) t;