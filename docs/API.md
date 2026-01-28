# Song Ranker - API Reference

**Last Updated**: January 2025  
**Purpose**: Documentation for database functions, stored procedures, and API endpoints  
**Status**: 🚧 **In Development**

---

## 🔧 **Database Functions**

### **Functions Overview**

All backend logic is implemented as PostgreSQL functions in Supabase. These functions can be called from the frontend via Supabase client.

---

## 📊 **Song Management Functions**

### **`get_all_songs()`**
**Purpose**: Retrieve all songs from the catalog

**Status**: 📋 **Planned**

**Returns**: Array of song objects

**Usage**:
```sql
SELECT * FROM get_all_songs();
```

**Parameters**: None

**Returns**:
```typescript
Array<{
  id: string;
  title: string;
  artist: string;
  created_at: string;
  updated_at: string;
}>
```

---

## 🎯 **Comparison Functions**

### **`record_comparison(song_a_id, song_b_id, winner_id, user_id)`**
**Purpose**: Record a pairwise comparison result

**Status**: 📋 **Planned**

**Parameters**:
- `song_a_id` (uuid): First song in comparison
- `song_b_id` (uuid): Second song in comparison
- `winner_id` (uuid): ID of the winning song
- `user_id` (uuid): ID of the user making the comparison

**Returns**: Comparison record

**Usage**:
```sql
SELECT * FROM record_comparison(
  'song-a-uuid',
  'song-b-uuid',
  'winner-uuid',
  'user-uuid'
);
```

---

## 📈 **Ranking Functions**

### **`calculate_rankings(user_id)`**
**Purpose**: Calculate rankings for a user based on their comparisons using Bradley-Terry model

**Status**: 📋 **Planned**

**Parameters**:
- `user_id` (uuid): User ID to calculate rankings for

**Returns**: Array of ranked songs

**Usage**:
```sql
SELECT * FROM calculate_rankings('user-uuid');
```

**Algorithm**: Bradley-Terry Model

---

### **`get_user_rankings(user_id)`**
**Purpose**: Retrieve current rankings for a user

**Status**: 📋 **Planned**

**Parameters**:
- `user_id` (uuid): User ID

**Returns**: Array of ranked songs

**Usage**:
```sql
SELECT * FROM get_user_rankings('user-uuid');
```

---

## 🔐 **Authentication & Security**

**Status**: 📋 **Planned**

- Row Level Security (RLS) policies will be documented here
- Authentication functions (if any) will be documented here

---

## 📝 **Frontend Integration**

### **Calling Functions from Frontend**

Functions can be called using Supabase RPC:

```typescript
import { supabase } from '@/lib/supabase';

// Call a database function
const { data, error } = await supabase.rpc('function_name', {
  param1: 'value1',
  param2: 'value2'
});
```

---

## 📋 **Function Status**

| Function Name | Status | Description |
|--------------|--------|-------------|
| `get_all_songs` | 📋 Planned | Get all songs |
| `record_comparison` | 📋 Planned | Record comparison |
| `calculate_rankings` | 📋 Planned | Calculate rankings |
| `get_user_rankings` | 📋 Planned | Get user rankings |

**Legend**:
- ✅ **Implemented** - Function is complete and tested
- 🚧 **In Progress** - Function is being developed
- 📋 **Planned** - Function is planned but not started

---

**Last Updated**: January 2025
