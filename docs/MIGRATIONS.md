# Song Ranker - Database Migrations

**Last Updated**: January 2025  
**Purpose**: Track all database migrations and schema changes  
**Status**: 🚧 **In Development**

---

## 📋 **Migration History**

### **Migration 001: Initial Schema Setup**
**Date**: TBD  
**Status**: 📋 **Planned**

**Description**: Initial database schema creation

**Changes**:
- Create `songs` table
- Create `comparisons` table
- Create `rankings` table
- Set up basic indexes
- Configure Row Level Security (RLS)

**SQL**:
```sql
-- Migration SQL will be added here
```

**Rollback**:
```sql
-- Rollback SQL will be added here
```

---

## 🔄 **Migration Guidelines**

### **Naming Convention**
- Format: `001_description.sql`, `002_description.sql`, etc.
- Use descriptive names that explain the change
- Keep migrations sequential

### **Best Practices**
1. **Always include rollback scripts** - Document how to reverse the migration
2. **Test migrations** - Test both forward and backward migrations
3. **Version control** - Commit migrations to git before applying
4. **Document changes** - Update this file with each migration
5. **Supabase deployment** - Apply migrations through Supabase SQL Editor or CLI

### **Migration Workflow**
1. Create migration SQL file
2. Test locally (if possible) or in Supabase staging
3. Document in this file
4. Apply to production Supabase instance
5. Commit to git repository

---

## 📝 **Notes**

- Migrations are applied directly to Supabase PostgreSQL database
- Use Supabase SQL Editor or Supabase CLI for applying migrations
- Always backup database before applying migrations in production

---

**Last Updated**: January 2025
