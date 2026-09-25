"""Search queries over the loaded export. Return plain data; the CLI and the MCP stub format it."""
from archive import connect, table_names


def search_shares(query, limit=None):
    con = connect()
    if "shares" not in table_names(con):
        return []
    q = f"%{query.lower()}%"
    sql = """SELECT Date, ShareCommentary, ShareLink FROM shares
             WHERE (LOWER(ShareCommentary) LIKE ? OR LOWER(SharedUrl) LIKE ?) AND Date IS NOT NULL
             ORDER BY Date DESC"""
    rows = con.execute(sql + (f" LIMIT {int(limit)}" if limit else ""), (q, q)).fetchall()
    return [{"date": r[0], "commentary": r[1] or "", "link": r[2]} for r in rows]


def find_connections(title="", company=""):
    con = connect()
    if "connections" not in table_names(con):
        return []
    sql, params = "SELECT [First Name], [Last Name], Position, Company, URL FROM connections WHERE 1=1", []
    if title:
        sql += " AND LOWER(Position) LIKE ?"
        params.append(f"%{title.lower()}%")
    if company:
        sql += " AND LOWER(Company) LIKE ?"
        params.append(f"%{company.lower()}%")
    sql += " ORDER BY Position"
    return [{"first_name": r[0], "last_name": r[1], "position": r[2], "company": r[3], "url": r[4]}
            for r in con.execute(sql, params).fetchall()]


def search_connections_keywords(keywords):
    con = connect()
    if "connections" not in table_names(con):
        return []
    out = []
    for first, last, pos, comp, url in con.execute(
            "SELECT [First Name], [Last Name], Position, Company, URL FROM connections").fetchall():
        combined = f"{pos or ''} {comp or ''}".lower()
        if all(kw.lower() in combined for kw in keywords):
            out.append({"first_name": first, "last_name": last, "position": pos, "company": comp, "url": url})
    return out


def search_comments(query):
    con = connect()
    if "comments" not in table_names(con):
        return []
    return [{"date": r[0], "comment": r[1] or ""} for r in con.execute(
        "SELECT Date, Comment FROM comments WHERE LOWER(Comment) LIKE ? ORDER BY Date DESC",
        (f"%{query.lower()}%",)).fetchall()]


def stats():
    con = connect()
    names = table_names(con)
    return {t: (con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in names else 0)
            for t in ("shares", "connections", "comments", "reactions", "messages", "invitations")}
