from flask import Flask, render_template, request, send_file, jsonify
import io, base64, re, requests, os, pdfkit
from odoo_client import OdooClient

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config (Render Free Compatible) ----------------
PDFKIT_CONFIG = pdfkit.configuration()  # Auto path detection — works both locally and Render

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

    lead_id = odoo.create_lead(lead_data)
    print(f"✅ Lead created in Odoo: {lead_id}")
    return lead_id


# ---------------- ROUTES ----------------

# 🔹 HubSpot → Odoo Webhook
@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    data = request.json
    print("🔥 HubSpot payload received:", data)

    values_list = []
    for event in data.get("events", []):
        values_list = event.get("formSubmission", {}).get("values", [])
        if values_list:
            break

    if not values_list and "properties" in data:
        values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]

    if not values_list:
        print("⚠️ No valid HubSpot form data found.")
        return jsonify({"status": "no data found"}), 400

    parsed_data = parse_values(values_list)
    print("✅ Parsed HubSpot data:", parsed_data)

    create_odoo_lead(parsed_data, lead_type="IQL")
    return jsonify({"status": "success"})


# 🔹 Get Project Details from Odoo
@app.route("/project/details", methods=["GET"])
def project_details():
    project_name = request.args.get("project_name")
    project_description = request.args.get("project_description")
    project_category = request.args.get("project_category")

    if not project_name or not project_description or not project_category:
        return jsonify({"status": "error", "message": "Missing project info"}), 400

    domain = [
        ['x_studio_project_name_1', '=', project_name],
        ['x_studio_project_description_1', '=', project_description],
        ['x_studio_project_category_1', '=', project_category]
    ]
    print("🔹 Searching in Odoo with domain:", domain)

    try:
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
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# 🔹 Lead Won Check
@app.route("/lead/won", methods=["GET"])
def lead_won():
    lead_name = request.args.get("lead_name", "").strip()

    domain = [['stage_id.name', 'ilike', 'won']]
    if lead_name:
        domain.append(['name', 'ilike', lead_name])

    print("🔹 Lead Won search domain:", domain)
    try:
        lead_ids = odoo.models.execute_kw(
            odoo.DB, odoo.uid, odoo.PASSWORD,
            'crm.lead', 'search',
            [domain]
        )
        if lead_ids:
            return jsonify({"status": "success", "message": f"Lead {lead_name or ''} is marked as won"})
        else:
            return jsonify({"status": "not found", "message": "No won lead found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# 🔹 RFQ Form (HTML)
@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    project_name = request.args.get("project_name", "")
    description = request.args.get("project_description", "")
    category = request.args.get("project_category", "")
    return render_template("rfq_form.html",
                           lead_id=lead_id,
                           project_name=project_name,
                           description=description,
                           category=category)


# 🔹 RFQ Submission (PDF + Upload)
@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = request.form.get("lead_id")
    if not lead_id or not lead_id.isdigit():
        return "Invalid or missing lead_id", 400
    lead_id = int(lead_id)

    project_name = request.form.get("project_name", "Project")
    safe_project_name = re.sub(r'[^A-Za-z0-9_-]', '_', project_name.strip())

    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")

    pdf_html = f"""
    <html><head><style>
        body {{ font-family: Arial; font-size: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #ccc; padding: 6px; }}
        th {{ background-color: #f5f5f5; }}
    </style></head>
    <body>
    <h2>RFQ Document for {project_name}</h2>
    <table><tr><th>Field</th><th>Value</th></tr>
    """
    for name, value in zip(field_names, field_values):
        pdf_html += f"<tr><td>{name}</td><td>{value}</td></tr>"
    pdf_html += "</table></body></html>"

    try:
        pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)
    except Exception as e:
        return f"PDF generation failed: {e}", 500

    pdf_filename = f"RFQ_{safe_project_name}_{lead_id}.pdf"
    return send_file(io.BytesIO(pdf_bytes), download_name=pdf_filename, as_attachment=True)


# ---------------- Main ----------------
if __name__ == "__main__":
    print("🚀 Flask server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
