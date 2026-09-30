# Code Review Output Example

> This is an example output from the `code-review-expert` skill reviewing the agentic-engineering backend.

## Review Summary

**Scope:** Backend API (Express.js + TypeScript + SQLite)  
**Files Reviewed:** 5 source files  
**Date:** February 2026

### Issue Counts

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 0 | Critical/Security |
| P1 | 2 | High priority |
| P2 | 8 | Medium priority |
| P3 | 4 | Low priority/suggestions |

---

## P1 Issues (High Priority)

### P1-1: Missing Input Validation on `/api/calculate-costs`

**File:** `backend/src/routes/costs.ts`  
**Lines:** 95-180

**Problem:** The endpoint accepts `profile`, `tripParams`, and `resortIds` from the request body without validation. Invalid data could cause runtime errors or unexpected behavior.

**Missing Validations:**
- `profile.members` not verified as array
- `tripParams.startDate` and `endDate` not validated as valid date strings
- `resortIds` not verified as non-empty string array
- Member fields (`age`, `needsRental`, `needsLessons`) not type-checked

**Risk:** Malformed requests crash the server or produce incorrect results.

**Recommendation:** Add input validation before processing:
```
if (!isValidDateString(startDate)) {
  return 400 "Invalid startDate format"
}
if (endDate <= startDate) {
  return 400 "endDate must be after startDate"
}
```

---

### P1-2: No Error Handling on Database Queries

**Files:** `backend/src/routes/resorts.ts`, `backend/src/routes/costs.ts`  
**Lines:** Multiple

**Problem:** Database queries execute without try/catch. If the database fails (connection lost, corruption, timeout), the error propagates unhandled.

**Code Pattern Found:**
```
const rows = db.prepare(query).all(...params);  // No try/catch
res.json(rows);
```

**Risk:** Unhandled exceptions crash the server or leak internal error details.

**Recommendation:** Wrap all DB operations in try/catch and use centralized error middleware:
```
try {
  const rows = db.prepare(query).all(...params);
  res.json(rows);
} catch (err) {
  next(err);  // Forward to error handler
}
```

---

## P2 Issues (Medium Priority)

### P2-1: N+1 Query Pattern in Cost Calculation

**File:** `backend/src/routes/costs.ts`  
**Lines:** 160-180

**Problem:** Each resort ID triggers a separate database query inside a loop.

**Code Pattern:**
```
for (const id of resortIds) {
  const resort = db.prepare('SELECT * FROM resorts WHERE id = ?').get(id);
  // process...
}
```

**Impact:** Performance degrades linearly with number of resorts.

**Recommendation:** Batch fetch all resorts in one query:
```
const placeholders = resortIds.map(() => '?').join(',');
const resorts = db.prepare(`SELECT * FROM resorts WHERE id IN (${placeholders})`).all(...resortIds);
```

---

### P2-2: URL Injection Risk in Deep Links

**File:** `backend/src/routes/resorts.ts`  
**Lines:** 260-290

**Problem:** Query parameters are concatenated directly into URLs without encoding.

**Code Pattern:**
```
const url = `https://google.com/travel/flights?q=${origin} to ${destination}`;
```

**Risk:** Special characters (spaces, &, ?) could break URLs or enable injection.

**Recommendation:** Use URLSearchParams for safe encoding:
```
const params = new URLSearchParams({ q: `${origin} to ${destination}` });
const url = `https://google.com/travel/flights?${params}`;
```

---

### P2-3: Duplicate Type Definitions

**Files:** `backend/src/routes/costs.ts`, `backend/src/routes/resorts.ts`, `backend/src/services/fitScore.ts`

**Problem:** Same TypeScript interfaces defined in multiple files (FamilyProfile, Resort, etc.).

**Risk:** Types diverge over time, causing subtle bugs.

**Recommendation:** Centralize types in a single `types.ts` file and import everywhere.

---

### P2-4: Missing Centralized Error Handler

**File:** `backend/src/index.ts`

**Problem:** No Express error middleware to catch and format errors consistently.

**Risk:** Errors return inconsistent formats or leak stack traces.

**Recommendation:** Add error middleware as the last middleware:
```
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Internal server error' });
});
```

---

### P2-5: Date Ordering Not Validated

**File:** `backend/src/routes/costs.ts`

**Problem:** `endDate` before `startDate` produces negative day counts.

**Recommendation:** Validate date ordering and return 400 if invalid.

---

### P2-6: Empty Arrays Not Handled

**File:** `backend/src/routes/costs.ts`

**Problem:** Empty `resortIds` array or `profile.members` array not rejected.

**Recommendation:** Return 400 for empty required arrays.

---

### P2-7: Non-String Resort IDs Not Rejected

**File:** `backend/src/routes/costs.ts`

**Problem:** `resortIds` could contain numbers or objects without validation.

**Recommendation:** Validate all elements are non-empty strings.

---

### P2-8: Missing Origin City Validation

**File:** `backend/src/routes/costs.ts`

**Problem:** `tripParams.originCity` not validated as required field.

**Recommendation:** Return 400 if originCity is missing or empty.

---

## P3 Issues (Suggestions)

### P3-1: Magic Numbers in Season Logic

**File:** `backend/src/routes/costs.ts`  
**Function:** `getSeason()`

**Suggestion:** Extract date ranges to named constants for readability.

---

### P3-2: No Request Logging

**Suggestion:** Add request logging middleware for debugging and monitoring.

---

### P3-3: CORS Configuration Too Permissive

**File:** `backend/src/index.ts`

**Suggestion:** Restrict CORS origins in production.

---

### P3-4: No Health Check Timeout

**File:** `backend/src/index.ts`

**Suggestion:** Health check could verify database connectivity.

---

## Resolution Summary

After review, the following fixes were applied:

| Issue | Status | Fix Applied |
|-------|--------|-------------|
| P1-1 | ✅ Fixed | Added comprehensive input validation |
| P1-2 | ✅ Fixed | Added try/catch + centralized error handler |
| P2-1 | ✅ Fixed | Batched DB queries with WHERE IN |
| P2-2 | ✅ Fixed | Used URLSearchParams for URL encoding |
| P2-3 | ✅ Fixed | Created `backend/src/types.ts` |
| P2-4 | ✅ Fixed | Added error middleware to index.ts |
| P2-5 | ✅ Fixed | Added date ordering validation |
| P2-6 | ✅ Fixed | Return 400 for empty arrays |
| P2-7 | ✅ Fixed | Validate string types in arrays |
| P2-8 | ✅ Fixed | Validate originCity required |
| P3-* | Deferred | Logged for future improvement |

## Test Coverage After Fixes

| Metric | Value |
|--------|-------|
| Total Tests | 81 |
| Line Coverage | 96.59% |
| Branch Coverage | 91.09% |
| All Tests Passing | ✅ |
