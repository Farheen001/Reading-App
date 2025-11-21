import runpy
import os

# Small launcher to run the app located inside the 'Reading App' folder
# This avoids problems when Streamlit Cloud (or other systems) split paths
# on spaces. Set the Cloud "main module" to `streamlit_app.py`.

HERE = os.path.dirname(__file__)
app_path = os.path.join(HERE, "Reading App", "app.py")

if not os.path.exists(app_path):
    raise FileNotFoundError(f"Could not find nested app at: {app_path}")

# Execute the nested app as a script
runpy.run_path(app_path, run_name="__main__")
