local http = require "resty.http"
-- change this
local wake_url="http://192.168.1.42:10000/go/server"
local connect_timeout_ms = 2000
local send_timeout_ms = 12000
local read_timeout_ms = 12000
-- ************ 
local httpc = http.new()
httpc:set_timeouts(connect_timeout_ms, send_timeout_ms, read_timeout_ms)
local res,err = httpc:request_uri(wake_url, { method = "GET" })

if err then
    ngx.log(ngx.ERR, "wake request failed: ", err)
else
    ngx.log(ngx.ALERT,"wake request reply: ", res.body)
end



