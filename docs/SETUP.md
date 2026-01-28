# Song Ranker - Backend Setup Guide

**Last Updated**: January 2025  
**Purpose**: Instructions for setting up and working with the backend repository  
**Status**: ✅ **ACTIVE**

---

## 🎯 **Overview**

This repository contains the backend code for Song Ranker, including:
- Database schema definitions
- SQL migrations
- Database functions and stored procedures
- Backend logic for Supabase PostgreSQL

**Database Host**: Supabase  
**Project URL**: https://loqddpjjjakaqgtuvoyn.supabase.co  
**Repository**: https://github.com/svadrutk/songranker-backend.git

---

## 📋 **Prerequisites**

- Access to Supabase project (https://loqddpjjjakaqgtuvoyn.supabase.co)
- Git installed
- Supabase CLI (optional, for local development)

---

## 🚀 **Initial Setup**

### **1. Clone the Repository**

```bash
git clone https://github.com/svadrutk/songranker-backend.git
cd songranker-backend
```

### **2. Connect to Supabase**

You can work with the database in two ways:

#### **Option A: Supabase Dashboard (Recommended for now)**
1. Go to https://loqddpjjjakaqgtuvoyn.supabase.co
2. Navigate to SQL Editor
3. Run SQL scripts directly

#### **Option B: Supabase CLI (For advanced workflows)**
1. Install Supabase CLI: `npm install -g supabase`
2. Link to project: `supabase link --project-ref loqddpjjjakaqgtuvoyn`
3. Run migrations: `supabase db push`

---

## 📁 **Repository Structure**

```
songranker-backend/
├── docs/                    # Documentation
│   ├── SCHEMA.md           # Database schema
│   ├── MIGRATIONS.md       # Migration history
│   ├── API.md              # Function/API reference
│   └── SETUP.md            # This file
├── migrations/             # SQL migration files (to be created)
│   └── 001_initial_schema.sql
└── functions/              # SQL function files (to be created)
    └── ranking_functions.sql
```

---

## 🔧 **Development Workflow**

### **Creating a Migration**

1. **Create migration file**:
   ```bash
   # Create file: migrations/XXX_description.sql
   ```

2. **Write SQL**:
   ```sql
   -- migrations/001_initial_schema.sql
   CREATE TABLE songs (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     title TEXT NOT NULL,
     artist TEXT NOT NULL,
     created_at TIMESTAMP DEFAULT NOW(),
     updated_at TIMESTAMP DEFAULT NOW()
   );
   ```

3. **Test in Supabase**:
   - Open Supabase SQL Editor
   - Paste and run the migration SQL
   - Verify it works correctly

4. **Document**:
   - Update `docs/MIGRATIONS.md` with migration details
   - Update `docs/SCHEMA.md` if schema changed

5. **Commit**:
   ```bash
   git add migrations/001_initial_schema.sql
   git add docs/MIGRATIONS.md
   git commit -m "Add initial schema migration"
   git push
   ```

### **Creating a Database Function**

1. **Create function file** (optional, or add to existing):
   ```bash
   # Create: functions/ranking_functions.sql
   ```

2. **Write function SQL**:
   ```sql
   CREATE OR REPLACE FUNCTION get_all_songs()
   RETURNS TABLE (
     id UUID,
     title TEXT,
     artist TEXT,
     created_at TIMESTAMP,
     updated_at TIMESTAMP
   ) AS $$
   BEGIN
     RETURN QUERY
     SELECT s.id, s.title, s.artist, s.created_at, s.updated_at
     FROM songs s
     ORDER BY s.title;
   END;
   $$ LANGUAGE plpgsql;
   ```

3. **Deploy to Supabase**:
   - Open Supabase SQL Editor
   - Paste and run the function SQL

4. **Document**:
   - Update `docs/API.md` with function details

5. **Commit**:
   ```bash
   git add functions/ranking_functions.sql
   git add docs/API.md
   git commit -m "Add get_all_songs function"
   git push
   ```

---

## 🗄️ **Database Access**

### **Connection Details**

- **Host**: db.loqddpjjjakaqgtuvoyn.supabase.co
- **Database**: postgres
- **Port**: 5432
- **Access**: Through Supabase Dashboard or connection string

### **Getting Connection String**

1. Go to Supabase Dashboard
2. Navigate to Settings → Database
3. Copy connection string (use connection pooling for production)

---

## 📚 **Documentation Standards**

### **When to Update Documentation**

- **SCHEMA.md**: After any table, column, or relationship changes
- **MIGRATIONS.md**: After creating a new migration
- **API.md**: After creating or modifying a function
- **SETUP.md**: When setup process changes

### **Documentation Format**

- Use clear headings and structure
- Include status indicators (✅ 🚧 📋)
- Provide code examples
- Document parameters and return types
- Include usage examples

---

## 🔐 **Security Notes**

- Never commit sensitive credentials to git
- Use Supabase environment variables for connection strings
- Row Level Security (RLS) policies should be documented in SCHEMA.md
- Always test migrations in a safe environment first

---

## 🐛 **Troubleshooting**

### **Common Issues**

**Issue**: Can't connect to Supabase  
**Solution**: Verify you have access to the project dashboard

**Issue**: Migration fails  
**Solution**: Check SQL syntax, verify table doesn't already exist, check for dependencies

**Issue**: Function not found  
**Solution**: Verify function was created in Supabase, check function name spelling

---

## 📝 **Notes**

- All backend work is deployed directly to Supabase
- This repository serves as version control and documentation
- SQL files in this repo should match what's deployed to Supabase
- Keep documentation in sync with actual database state

---

## 🔗 **Related Documentation**

- **Frontend Repository**: https://github.com/svadrutk/songranker-frontend.git
- **Frontend Docs**: See `key_documentation/` folder in frontend repo
- **Supabase Dashboard**: https://loqddpjjjakaqgtuvoyn.supabase.co

---

**Last Updated**: January 2025
