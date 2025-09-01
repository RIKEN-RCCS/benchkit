import os
import sys

# Retrieve the API key from environment variable (needed in receive.py)
EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")

# Exit if the API key is not set
if not EXPECTED_API_KEY:
    print("ERROR: RESULT_SERVER_KEY is not set.", file=sys.stderr)
    sys.exit(1)

# Import Flask and route blueprints
from flask import Flask, render_template
from routes.receive import receive_bp
from routes.results import results_bp
from routes.upload_tgz import upload_bp

# Create the Flask app and specify the templates folder
app = Flask(__name__, template_folder="templates")

# Register route blueprints
app.register_blueprint(receive_bp)
app.register_blueprint(results_bp)
app.register_blueprint(upload_bp)

@app.route('/hard_env/<sys>')
def hard_env(sys):
    return render_template('hard_env.html', sys=sys)

#---------------------------------------------------------------------------------
# Run the Flask app only if this script is run directly (not imported as a module)
if __name__ == "__main__":
    # Ensure the directory to store received files exists
    os.makedirs("received", exist_ok=True)
    # Start the server, listening on all interfaces at port 8800
    app.run(host="0.0.0.0", port=8800)
