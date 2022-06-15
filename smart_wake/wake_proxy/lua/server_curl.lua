-- change this -- max time should correspond to backoff time in sleepy_nas
local wake_url = "http://192.168.1.42:10000/go/server"
local curl_max_time = 12
-- ************* 
local curl = "curl -Ss -q --max-time "..curl_max_time.." "..wake_url
ngx.log(ngx.ALERT, "Waking server via curl: ",curl)
os.execute(curl)

