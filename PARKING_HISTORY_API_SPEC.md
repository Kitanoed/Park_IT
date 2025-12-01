# Parking History API - Technical Specification

## 1. API Endpoint Specification

### Endpoint Details

| Property | Value |
|----------|-------|
| **Endpoint** | `/api/admin/parking/history/` |
| **Method** | `GET` |
| **Authentication** | Required (Session-based, Admin role only) |
| **Response Format** | JSON (Paginated) |
| **Content-Type** | `application/json` |

### Authentication & Authorization

- **Authentication**: Session-based authentication required
  - User must have valid session with `access_token` and `user_id`
- **Authorization**: Admin role required
  - User's `role` field must equal `'admin'` (case-insensitive)
- **Error Responses**:
  - `401 Unauthorized`: Missing or invalid authentication
  - `403 Forbidden`: User does not have admin privileges

### Query Parameters

All parameters are optional. Multiple filters can be combined (additive filtering).

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `search_plate` | String | Partial match against `vehicle.plate` (case-insensitive) | `ABC-1234` |
| `date_from` | Date (YYYY-MM-DD) | Filter sessions where `entry_time >= date_from` | `2024-01-15` |
| `date_to` | Date (YYYY-MM-DD) | Filter sessions where `entry_time <= date_to` | `2024-01-20` |
| `lot_name` | String | Exact match against `parking_lot.name` | `Lot A - Main` |
| `status` | String | Filter by session status: `'Active'` or `'Completed'` | `Completed` |
| `page` | Integer | Page number (default: 1, minimum: 1) | `2` |
| `page_size` | Integer | Items per page (default: 10, maximum: 100) | `25` |

### Request Example

```
GET /api/admin/parking/history/?search_plate=ABC&date_from=2024-01-15&date_to=2024-01-20&status=Completed&page=1&page_size=10
```

### Response Structure

#### Success Response (200 OK)

```json
{
  "results": [
    {
      "session_id": 123,
      "plate_number": "ABC-1234",
      "lot_name": "Lot A - Main",
      "entry_time": "2024-01-15T08:30:00Z",
      "exit_time": "2024-01-15T12:45:00Z",
      "duration": "4h 15m",
      "status": "Completed"
    },
    {
      "session_id": 124,
      "plate_number": "XYZ-5678",
      "lot_name": "North Gate Extension",
      "entry_time": "2024-01-15T09:15:00Z",
      "exit_time": null,
      "duration": "0h 0m",
      "status": "Active"
    }
  ],
  "count": 2,
  "page": 1,
  "page_size": 10,
  "total_pages": 1
}
```

#### Error Response (401 Unauthorized)

```json
{
  "error": "Authentication required"
}
```

#### Error Response (403 Forbidden)

```json
{
  "error": "Admin privileges required"
}
```

#### Error Response (500 Internal Server Error)

```json
{
  "error": "Database error: <error message>"
}
```

### Data Aggregation Logic

1. **Session Construction**:
   - Each session is built from an `entry` record in `entries_exits` table
   - Entry records are identified by `action = 'entry'`
   - Corresponding exit records are found by matching:
     - Same `vehicle_id`
     - `action = 'exit'`
     - `exit.time >= entry.time` (exit must occur after entry)

2. **Status Determination**:
   - `"Active"`: No corresponding exit record found
   - `"Completed"`: Exit record exists

3. **Duration Calculation**:
   - Format: `"Xh Ym"` (e.g., `"4h 15m"`, `"0h 30m"`)
   - Calculated from `entry_time` and `exit_time`
   - Returns `"0h 0m"` for Active sessions

4. **Table Joins**:
   - `entries_exits` (primary) → `vehicle` (via `vehicle_id`) → `plate_number`
   - `entries_exits` (primary) → `parking_lot` (via `lot_id`) → `lot_name`

### Filtering Logic

Filters are applied in the following order:

1. **Date Range Filter**: Applied to `entries_exits.time` at query level
2. **Plate Search**: Applied to `vehicle.plate` using ILIKE pattern matching
3. **Lot Name Filter**: Applied to `parking_lot.name` using exact match
4. **Status Filter**: Applied after session construction (Active/Completed)

### Pagination

- Default page size: 10 items
- Maximum page size: 100 items
- Page numbering starts at 1
- Results are sorted by `entry_time` (most recent first)

---

## 2. Database Indexing Strategy

### Index Creation SQL

See `database_indexes.sql` for complete SQL script.

### Index Summary

#### entries_exits Table

| Index Name | Columns | Purpose |
|------------|---------|---------|
| `idx_entries_exits_time` | `time` | Date range filtering |
| `idx_entries_exits_vehicle_id` | `vehicle_id` | Foreign key join optimization |
| `idx_entries_exits_lot_id` | `lot_id` | Foreign key join optimization |
| `idx_entries_exits_action` | `action` | Status calculation (entry/exit matching) |
| `idx_entries_exits_lot_time` | `lot_id, time` | Composite: lot + date filtering |
| `idx_entries_exits_vehicle_time` | `vehicle_id, time` | Composite: vehicle + date filtering |
| `idx_entries_exits_action_vehicle_time` | `action, vehicle_id, time` | Composite: entry/exit matching |

#### vehicle Table

| Index Name | Columns | Purpose |
|------------|---------|---------|
| `idx_vehicle_plate` | `plate` | Plate number search |
| `idx_vehicle_plate_lower` | `LOWER(plate)` | Case-insensitive plate search (PostgreSQL) |

#### parking_lot Table

| Index Name | Columns | Purpose |
|------------|---------|---------|
| `idx_parking_lot_name` | `name` | Lot name filtering |

### Performance Considerations

1. **Index Maintenance**: Indexes improve query performance but slightly slow INSERT operations
2. **Query Optimization**: Composite indexes are designed for common query patterns
3. **ANALYZE**: Run `ANALYZE` after creating indexes to update statistics:
   ```sql
   ANALYZE entries_exits;
   ANALYZE vehicle;
   ANALYZE parking_lot;
   ```

---

## 3. Implementation Notes

### Session Matching Algorithm

The API matches entry and exit records using the following logic:

1. Fetch all entry records (`action = 'entry'`) matching date filters
2. For each entry:
   - Find the earliest exit record for the same vehicle where `exit.time >= entry.time`
   - If no exit found, session status is `"Active"`
   - If exit found, session status is `"Completed"`

### Edge Cases Handled

- **Missing vehicle**: Sessions with invalid `vehicle_id` are excluded
- **Missing lot**: Sessions with invalid `lot_id` are excluded
- **Null timestamps**: Handled gracefully in duration calculation
- **Timezone handling**: ISO format timestamps with timezone support

### Security Considerations

- All authentication checks occur before database queries
- Admin role verification prevents unauthorized access
- SQL injection protection via Supabase query builder
- Input validation on all query parameters

---

## 4. Usage Examples

### Example 1: Get all active sessions

```
GET /api/admin/parking/history/?status=Active
```

### Example 2: Search by plate with date range

```
GET /api/admin/parking/history/?search_plate=ABC&date_from=2024-01-15&date_to=2024-01-20
```

### Example 3: Filter by lot with pagination

```
GET /api/admin/parking/history/?lot_name=Lot%20A%20-%20Main&page=2&page_size=25
```

### Example 4: Combined filters

```
GET /api/admin/parking/history/?search_plate=XYZ&date_from=2024-01-10&lot_name=North%20Gate%20Extension&status=Completed&page=1&page_size=10
```

---

## 5. Testing Checklist

- [ ] Authentication: Unauthenticated requests return 401
- [ ] Authorization: Non-admin users return 403
- [ ] Date filtering: `date_from` and `date_to` work correctly
- [ ] Plate search: Partial matching works (case-insensitive)
- [ ] Lot filtering: Exact match filtering works
- [ ] Status filtering: Active and Completed filters work
- [ ] Pagination: Page and page_size parameters work
- [ ] Session matching: Entry/exit pairs matched correctly
- [ ] Duration calculation: Correct format and values
- [ ] Edge cases: Null values, missing records handled

---

## 6. Future Enhancements

- [ ] Add sorting parameter (by entry_time, duration, etc.)
- [ ] Add export functionality (CSV, Excel)
- [ ] Add caching layer for frequently accessed data
- [ ] Add rate limiting for API endpoint
- [ ] Add request logging and analytics

