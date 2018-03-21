import sys, psycopg2, datetime, configparser, re, requires_auth
from flask import Flask, json
from flask_restful import Resource, Api

# this will clear and close the connection
def clear_connection():
	if 'conn' in globals():
		global conn
		if hasattr(conn, 'close'):
			conn.close()
		conn = None

	if 'cur' in globals():
		global cur
		if hasattr(cur, 'close'):
			cur.close()
		cur = None

# import configuration file containing our connection string
# app.ini looks like the following
#[db]
#	connection_string = dbname='iii' user='PUT_USERNAME_HERE' host='sierra-db.library-name.org' password='PUT_PASSWORD_HERE' port=1032
config = configparser.ConfigParser()
config.read('app.ini')

app = Flask(__name__)
api = Api(app)


#start auth0
def get_token_auth_header():
    """Obtains the access token from the Authorization Header
    """
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({"code": "authorization_header_missing",
                        "description":
                            "Authorization header is expected"}, 401)

    parts = auth.split()

    if parts[0].lower() != "bearer":
        raise AuthError({"code": "invalid_header",
                        "description":
                            "Authorization header must start with"
                            " Bearer"}, 401)
    elif len(parts) == 1:
        raise AuthError({"code": "invalid_header",
                        "description": "Token not found"}, 401)
    elif len(parts) > 2:
        raise AuthError({"code": "invalid_header",
                        "description":
                            "Authorization header must be"
                            " Bearer token"}, 401)

    token = parts[1]
    return token

def requires_auth(f):
    """Determines if the access token is valid
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()
        jsonurl = urlopen("https://"+AUTH0_DOMAIN+"/.well-known/jwks.json")
        jwks = json.loads(jsonurl.read())
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        if rsa_key:
            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=API_AUDIENCE,
                    issuer="https://"+AUTH0_DOMAIN+"/"
                )
            except jwt.ExpiredSignatureError:
                raise AuthError({"code": "token_expired",
                                "description": "token is expired"}, 401)
            except jwt.JWTClaimsError:
                raise AuthError({"code": "invalid_claims",
                                "description":
                                    "incorrect claims,"
                                    "please check the audience and issuer"}, 401)
            except Exception:
                raise AuthError({"code": "invalid_header",
                                "description":
                                    "Unable to parse authentication"
                                    " token."}, 400)

            _app_ctx_stack.top.current_user = payload
            return f(*args, **kwargs)
        raise AuthError({"code": "invalid_header",
                        "description": "Unable to find appropriate key"}, 400)
    return decorated
#end auth0


class GetItemInfo(Resource):
	def get(self, barcode):
		# we may want to consider moving the connection to the main application,
		# so that it remains open (but then we have to make sure we reconnect and test for timeouts, etc)

		#begin sanitize
		p = re.compile('\d+') #\d config excludes anything except 0-9
		b = p.findall(barcode) #this code only returns numbers=\d
		barcode = b[-1] #only need this whilst testing on port 5001; stores last list item, in this case a barcode
		if len(barcode) != 14:
			return 'barcode {} is not 14 characters long'.format(barcode)
		#length checker seems to freak out if you put a / in the middle of barcode


		try:
			# variable connection string should be defined in the imported config file
			conn = psycopg2.connect( config['db']['connection_string'] )
		except:
			print("unable to connect to the database")
			clear_connection()
			return
			# sys.exit(1)

		# here's our base query ...
		sql = """\
		---
		SELECT
		upper(p.call_number_norm) AS call_number_norm,
		v.field_content AS volume,
		i.location_code,
		i.item_status_code,
		b.best_title,
		c.due_gmt,
		i.inventory_gmt

		FROM
		sierra_view.phrase_entry AS e
		JOIN
		sierra_view.item_record_property AS p
		ON
		  e.record_id = p.item_record_id
		  JOIN sierra_view.item_record AS i
		ON
		  i.id = p.item_record_id
		LEFT OUTER JOIN sierra_view.checkout AS c
		ON
		  i.id = c.item_record_id
		-- This JOIN will get the Title and Author from the bib
		JOIN
		sierra_view.bib_record_item_record_link	AS l
		ON
		  l.item_record_id = e.record_id
		JOIN
		sierra_view.bib_record_property AS b
		ON
		  l.bib_record_id = b.bib_record_id

		LEFT OUTER JOIN
		sierra_view.varfield AS v
		ON
		  (i.id = v.record_id) AND (v.varfield_type_code = 'v')
		WHERE
		e.index_tag || e.index_entry = 'b' || LOWER('%s')
		--e.index_tag || e.index_entry = 'b' || LOWER('0989053860015')
		---
		"""

		# TODO
		# make sure we do some sort of sanitization of the barcode variable
		# before we send the query to the db (i think that psycopg2 does this by default)

		try:
			# cur = conn.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor)
			cur = conn.cursor()
			cur.execute(sql % (barcode))

		except:
			print("error connecting or running query sql")
			clear_connection()
			return
			# sys.exit(1) #don't use sys.exit; it will crash the python app rather than just returning error

		# output = cur.fetchone()
		output = cur.fetchone()

		# TODO
		# don't have the application crash when it can't find a barcode

		return { #'sql': sql % (barcode),
			'data': {'call_number_norm': output[0] or '',
				'volume': output[1] or '',
				'location_code': output[2] or '',
				'item_status_code': output[3] or '',
				'best_title': output[4] or '',
				'due_gmt': str(output[5]) or '',
				'inventory_gmt': str(output[6] or '')
			}
		}


class default(Resource):
	def get(self):
		return {'TODO': 'create a usage instruction page, or send an error',
			'example_url': 'http://127.0.0.1:5001/0989053860015'
		}
api.add_resource(GetItemInfo, '/<string:barcode>')
api.add_resource(default, '/')

if __name__ == '__main__':
	app.run(debug=False, port=5001)
