from flask import Flask, render_template, request, send_file, jsonify
import io, base64, requests, re, os
from weasyprint import HTML
from odoo_client import OdooClient

# ---------------- Flask App ----------------
app = Flask(__name__)

# ---------------- Environment Variables ----------------
ODOO_URL = os.environ.get("ODOO_URL")
ODOO_DB = os.environ.get("ODOO_DB")
ODOO_USERNAME = os.environ.get("ODOO_USERNAME")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD")
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY")

# ---------------- Odoo Client ----------------
odoo = OdooClient()  # your OdooClient.py should read credentials from env too

# ---------------- HubSpot → Odoo Lead ----------------
def parse_values(values_list):
    result = {}
    for item in values_list:
        result[item["name"]] = item["value"]
    return result

def create_odoo_lead(values, lead_type="IQL"):
    name = f"{values.get('firstname','')} {values.get('lastname','')}".strip() or "Unknown"
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

    lead_id = odoo.create_lead(lead_data)
    print(f"✅ Lead created: {name} ({email}), Type={lead_type}, ID={lead_id}")
    return lead_id

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
    create_odoo_lead(filtered_data)
    return jsonify({"status": "success"})

# ---------------- PDF Generation ----------------
@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = request.form.get("lead_id")
    try:
        lead_id = int(lead_id)
    except Exception:
        return "Invalid or missing lead_id", 400

    project_name = request.form.get("project_name", "Project")
    safe_project_name = re.sub(r'[^A-Za-z0-9_-]', '_', project_name.strip())
    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")

    html_content = f"<h2>RFQ Document for {project_name}</h2><table border='1'><tr><th>Field</th><th>Value</th></tr>"
    for name, value in zip(field_names, field_values):
        html_content += f"<tr><td>{name}</td><td>{value}</td></tr>"
    html_content += "</table>"

    pdf_bytes = HTML(string=html_content).write_pdf()
    return send_file(io.BytesIO(pdf_bytes),
                     download_name=f"RFQ_{safe_project_name}_{lead_id}.pdf",
                     as_attachment=True)

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

    project_ids = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'search',
        [domain]
    )

    if not project_ids:
        return jsonify({"status": "not found", "data": []})

    project_data = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'read',
        [project_ids[:1]],
        {'fields': [
            'name',
            'x_studio_project_name_1',
            'x_studio_project_description_1',
            'x_studio_project_category_1'
        ]}
    )
    return jsonify({"status": "success", "data": project_data})

if __name__ == "__main__":
    print("🚀 Flask server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
