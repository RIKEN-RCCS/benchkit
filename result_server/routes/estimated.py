from flask import Blueprint

from routes.estimated_detail_routes import register_estimated_detail_routes
from routes.estimated_list_routes import register_estimated_list_routes

estimated_bp = Blueprint("estimated", __name__)

register_estimated_list_routes(estimated_bp)
register_estimated_detail_routes(estimated_bp)
