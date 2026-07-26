import sqlite3

def optimize():
    print("Connecting to old DB...")
    old_db = sqlite3.connect('/home/natnael/dev/biocypher-kg-/output/.bioclaw.db')
    
    print("Creating new optimized DB...")
    new_db = sqlite3.connect('/home/natnael/dev/biocypher-kg-/output/.bioclaw_opt.db')
    
    new_db.executescript("""
        CREATE TABLE files (
            fid INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            grp TEXT,
            kind TEXT,
            sz INTEGER,
            mt REAL
        );
        
        -- Dictionary for entity types and heads
        CREATE TABLE dict (
            did INTEGER PRIMARY KEY,
            val TEXT UNIQUE COLLATE NOCASE
        );
        
        CREATE TABLE atoms (
            aid INTEGER PRIMARY KEY,
            fid INTEGER,
            hid INTEGER,  -- references dict(did)
            ln INTEGER,
            off INTEGER,
            blen INTEGER
        );
        
        CREATE TABLE ents (
            aid INTEGER,
            tid INTEGER,  -- references dict(did)
            eid TEXT COLLATE NOCASE
        );
    """)
    
    # Copy files
    print("Copying files...")
    files = old_db.execute("SELECT fid, path, grp, kind, sz, mt FROM files").fetchall()
    new_db.executemany("INSERT INTO files VALUES (?,?,?,?,?,?)", files)
    
    # Build dict
    print("Building dictionary...")
    heads = old_db.execute("SELECT DISTINCT head FROM atoms").fetchall()
    etypes = old_db.execute("SELECT DISTINCT etype FROM ents").fetchall()
    
    dict_vals = list(set([r[0] for r in heads] + [r[0] for r in etypes]))
    new_db.executemany("INSERT INTO dict (val) VALUES (?)", [(v,) for v in dict_vals])
    
    val_to_did = {v: i+1 for i, v in enumerate(dict_vals)}
    
    print("Copying atoms...")
    atoms = old_db.execute("SELECT aid, fid, head, ln, off, blen FROM atoms").fetchall()
    opt_atoms = [(a[0], a[1], val_to_did[a[2]], a[3], a[4], a[5]) for a in atoms]
    new_db.executemany("INSERT INTO atoms VALUES (?,?,?,?,?,?)", opt_atoms)
    
    print("Copying ents...")
    ents = old_db.execute("SELECT aid, etype, eid FROM ents").fetchall()
    opt_ents = [(e[0], val_to_did[e[1]], e[2]) for e in ents]
    new_db.executemany("INSERT INTO ents VALUES (?,?,?)", opt_ents)
    
    print("Creating indexes...")
    new_db.executescript("""
        CREATE INDEX ix_eid ON ents(eid);
        CREATE INDEX ix_tid ON ents(tid, eid);
        CREATE INDEX ix_hid ON atoms(hid);
        CREATE INDEX ix_afid ON atoms(fid);
        CREATE INDEX ix_eaid ON ents(aid);
    """)
    
    new_db.commit()
    print("VACUUMing...")
    new_db.execute("VACUUM")
    
    old_db.close()
    new_db.close()
    
    import os
    s1 = os.path.getsize('/home/natnael/dev/biocypher-kg-/output/.bioclaw.db')
    s2 = os.path.getsize('/home/natnael/dev/biocypher-kg-/output/.bioclaw_opt.db')
    print(f"Old size: {s1/1024/1024:.2f} MB")
    print(f"New size: {s2/1024/1024:.2f} MB")

if __name__ == "__main__":
    optimize()
