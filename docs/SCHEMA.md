# Song Ranker - Database Schema

**Last Updated**: January 2025  
**Purpose**: Complete database schema documentation  
**Status**: 🚧 **In Development**

---

## 📊 **Database Overview**

**Database Host**: Supabase PostgreSQL  
**Project URL**: https://loqddpjjjakaqgtuvoyn.supabase.co  
**Repository**: https://github.com/svadrutk/songranker-backend.git

---

## 🗂️ **Tables**

### **Songs Table**
**Purpose**: Stores the catalog of songs available for ranking

**Status**: 📋 **Planned**

```sql
-- Schema definition will be added here
```

**Columns**:
- `id` (uuid, primary key)
- `title` (text)
- `artist` (text)
- `created_at` (timestamp)
- `updated_at` (timestamp)

**Indexes**:
- TBD

**Relationships**:
- TBD

---

### **Comparisons Table**
**Purpose**: Stores pairwise comparison results from users

**Status**: 📋 **Planned**

```sql
-- Schema definition will be added here
```

**Columns**:
- `id` (uuid, primary key)
- `song_a_id` (uuid, foreign key)
- `song_b_id` (uuid, foreign key)
- `winner_id` (uuid, foreign key)
- `user_id` (uuid, foreign key)
- `created_at` (timestamp)

**Indexes**:
- TBD

**Relationships**:
- TBD

---

### **Rankings Table**
**Purpose**: Stores calculated rankings based on comparisons

**Status**: 📋 **Planned**

```sql
-- Schema definition will be added here
```

**Columns**:
- `id` (uuid, primary key)
- `song_id` (uuid, foreign key)
- `user_id` (uuid, foreign key)
- `rank` (integer)
- `score` (numeric)
- `created_at` (timestamp)
- `updated_at` (timestamp)

**Indexes**:
- TBD

**Relationships**:
- TBD

---

## 🔗 **Relationships**

```
Songs (1) ──< Comparisons (many) >── Songs (1)
Songs (1) ──< Rankings (many)
Users (1) ──< Comparisons (many)
Users (1) ──< Rankings (many)
```

---

## 🔐 **Row Level Security (RLS)**

**Status**: 📋 **Planned**

RLS policies will be documented here as they are implemented.

---

## 📝 **Notes**

- All tables use UUID primary keys
- Timestamps use `created_at` and `updated_at` pattern
- Foreign key relationships will be enforced at the database level

---

**Last Updated**: January 2025
