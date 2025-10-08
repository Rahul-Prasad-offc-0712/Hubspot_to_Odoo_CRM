from flask import Flask, render_template, request, send_file, jsonify
import pdfkit, io, base64, re
from odoo_client import OdooClient
import config

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config ----------------
PDFKIT_CONFIG = pdfkit.configuration()  # uses system path on Render

# ---------------- HubSpot → Odoo Lead ----------------
def parse_values(values_list):
    result = {}
    for item in values_list:
        result[item["name"]] = item["value"]
    return result

def create_odoo_lead(values, lead_type="IQL"):
    name = f"{values.get('firstname', '')} {values.get('lastname', '')}".strip() or "Unknown"
    email = values.get("email", "No Email")
    phone = values.get("phone", "")
    city = values.get("city", "")

    lead_data = {
        "name": name,
        "email_from": email,
        "phone": phone,
        "city": city,
        "description": f"Lead from HubSpot ({lead_type})",
    }

    if odoo.search_lead_by_email(email):
        print(f"⚠️ Duplicate lead skipped: {name} ({email})")
        return

    return odoo.create_lead(lead_data)

# ---------------- Routes ----------------
@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    data = request.json
    values_list = []
    for event in data.get("events", []):
        values_list = event.get("formSubmission", {}).get("values", [])
        if values_list:
            break
    if not values_list and "properties" in data:
        values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]
    if not values_list:
        return jsonify({"status": "no data found"}), 400
    filtered_data = parse_values(values_list)
    create_odoo_lead(filtered_data, lead_type="IQL")
    return jsonify({"status": "success"})

@app.route("/project/details", methods=["GET"])
def project_details():
    project_name = request.args.get("project_name")
    project_description = request.args.get("project_description")
    project_category = request.args.get("project_category")
    if not project_name or not project_description or not project_category:
        return jsonify({"status": "error", "message": "Missing project info"})
    domain = [
        ['x_studio_project_name_1', '=', project_name],
        ['x_studio_project_description_1', '=', project_description],
        ['x_studio_project_category_1', '=', project_category]
    ]
    project_ids = odoo.execute('crm.lead', 'search', [domain])
    if not project_ids:
        return jsonify({"status": "not found", "data": []})
    project_data = odoo.execute('crm.lead', 'read', [project_ids[:1]], {'fields': [
        'name','x_studio_project_name_1','x_studio_project_description_1','x_studio_project_category_1'
    ]})
    return jsonify({"status": "success", "data": project_data})

# ---------------- RFQ Form ----------------
@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    project_name = request.args.get("project_name", "") or ""
    description = request.args.get("project_description", "") or ""
    category = request.args.get("project_category", "") or ""
    return render_template("rfq_form.html", lead_id=lead_id,
                           project_name=project_name,
                           description=description,
                           category=category)

@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = int(request.form.get("lead_id"))
    project_name = request.form.get("project_name", "Project")
    safe_project_name = re.sub(r'[^A-Za-z0-9_-]', '_', project_name.strip())

    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")

    pdf_html = f"<html><head><meta charset='utf-8'/><style>body{{font-family:Arial;}}table{{border-collapse:collapse;}}th,td{{border:1px solid #ccc;padding:8px;}}</style></head><body>"
    pdf_html += f"<h2>RFQ Document for {project_name}</h2><table><tr><th>Field Name</th><th>Field Value</th></tr>"
    for name, value in zip(field_names, field_values):
        pdf_html += f"<tr><td>{name}</td><td>{value}</td></tr>"
    pdf_html += "</table></body></html>"

    pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)
    return send_file(io.BytesIO(pdf_bytes), download_name=f"RFQ_{safe_project_name}_{lead_id}.pdf", as_attachment=True)

# ---------------- Main ----------------
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
