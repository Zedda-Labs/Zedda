# SEC-P05: XSS Prevention Template for HTML Reports
#
# When implementing HTML report generation, follow this pattern to prevent
# Cross-Site Scripting (XSS) via malicious column names in CSV files:
#
# 1. ALWAYS HTML-ESCAPE column names before embedding in HTML:
#    from html import escape
#    safe_name = escape(col.name, quote=True)
#
# 2. USE TEMPLATE ENGINES with auto-escaping (preferred):
#    from jinja2 import Environment, select_autoescape
#    env = Environment(autoescape=select_autoescape(['html']))
#
# 3. NEVER interpolate raw strings into HTML:
#    # BAD:  f"<td>{col.name}</td>"
#    # GOOD: f"<td>{escape(col.name)}</td>"
#
# 4. SANITIZE CSS class names derived from column names:
#    import re
#    safe_class = re.sub(r'[^a-zA-Z0-9_-]', '_', col.name)
#
# Example safe render function:
#
#    from html import escape
#
#    def render_html(profile) -> str:
#        rows = []
#        for col in profile.columns:
#            rows.append(
#                f"<tr><td>{escape(col.name)}</td>"
#                f"<td>{escape(col.type_str)}</td>"
#                f"<td>{col.null_pct:.1f}%</td></tr>"
#            )
#        return HTML_TEMPLATE.format(rows="\n".join(rows))
