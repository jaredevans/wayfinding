# Make a hashed admin password
python - <<'PY'
from werkzeug.security import generate_password_hash
print(generate_password_hash("the_admin_password"))
PY

openssl rand -hex 32
