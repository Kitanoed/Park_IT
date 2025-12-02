-- Fix the entries_exits table sequence issue
-- This resets the sequence to the maximum ID + 1 to prevent duplicate key errors
-- Run this SQL in your Supabase SQL Editor

-- First, find the current maximum ID
-- SELECT MAX(id) FROM entries_exits;

-- Reset the sequence to the maximum ID + 1
-- This ensures the next auto-generated ID will be higher than any existing ID
SELECT setval(
    pg_get_serial_sequence('entries_exits', 'id'),
    COALESCE((SELECT MAX(id) FROM entries_exits), 0) + 1,
    false
);

-- Verify the sequence is set correctly
-- SELECT currval(pg_get_serial_sequence('entries_exits', 'id')) AS current_sequence_value;
-- SELECT MAX(id) FROM entries_exits AS max_id_in_table;

