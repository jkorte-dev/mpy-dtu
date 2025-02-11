import asyncio
import network
from datetime import datetime, timezone
import time

_CSS = const("""
:root {
    --prim-header-bg-color: green;
    --prim-cell-bg-color: chartreuse;
    --sec-header-bg-color: blue;
    --sec-cell-bg-color: deepskyblue;
}

div[data-theme='light'] {
    --prim-header-bg-color: green;
    --prim-cell-bg-color: chartreuse;
    --sec-header-bg-color: blue;
    --sec-cell-bg-color: deepskyblue;
}

div[data-theme='dark'] {
    --prim-header-bg-color: dimgrey;
    --prim-cell-bg-color: silver;
    --sec-header-bg-color: grey;
    --sec-cell-bg-color: whitesmoke;
}

.r-tb{
    width: 100%;
    display: table;
}
.r-tb-body{
    display: table-row-group;
}
.r-tb-row{
    display: table-row;
}
.r-tb-cell{
    display: table-cell;
    border: 1px solid #dddddd;
    padding: 8px;
    line-height: 1.42857143;
    vertical-align: top;
    font-family: Arial;
}
.hd1{
    background: var(--prim-header-bg-color);
    color: white;
    text-align: center;
}
.cl1{
    background: var(--prim-cell-bg-color);
    text-align: center;
}
.hd2{
    background: var(--sec-header-bg-color);
    color: white;
    text-align: center;
}
.cl2{
    background: var(--sec-cell-bg-color);
    text-align: center;
    display: block;
}
.half{
    width: 50%;
    margin: -1;
    margin-top: 10px;
    display: inline-block;
}
#content{
    margin: 5px;
}

.footer{
    background-color: lightgrey;
    margin: 6px;
    padding: 5px;
    font-family: Arial;
    text-align: center;
}

.event {
    margin: 6px;
}

@media only screen and (min-width: 420px) {
    .r-tb-cell {
        font-size: 30px;
    }
}

@media only screen and (orientation: landscape) {
    .r-tb-cell {
        font-size: 14px;
    }
}
""")

_JS = const("""
const spec = {
    'temperature': ['Temp. ', ' °C'],
    'power': ['Power ', ' W'],
    'voltage': ['U ', ' V'],
    'current': ['I ', ' A'],
    'frequency': ['F_AC ', ' Hz'],
    'energy_daily' : ['Yield Day', 'Wh'],
    'yield_today' : ['Yield Day', 'Wh'],
    'yield_total' : ['Yield Total', 'kWh', '0.001'],
    'energy_daily' : ['Yield Day', 'Wh'],
    'energy_total' : ['Yield Total', 'kWh', '0.001'],
    'efficiency' : ['Eff.', '%']
}

const specMap = new Map(Object.entries(spec));

document.addEventListener('DOMContentLoaded', function() {
    window.setInterval(updateContent, 10000);
});
function updateContent() {
    fetch(window.location + 'data')
        .then(response => response.json())
        .then(data => showData(data));
}


function showData(json) {
    let values = [json]
    json.power = json.phases[0].power;

    const content = document.getElementById('content');
    if (json.event['event_type'] == 'suntimes.sleeping') {
        theme = 'dark';
    } else {
        theme = 'light';
    }
    content.setAttribute('data-theme', theme);
    content.innerText = ''; // clear node first
    renderTable(content, values, json.inverter_name + ' ' + json.time + '\\n ' + new Date(), 'hd1', 'cl1');
    json.strings.forEach(item => {
        strNde = div('half');
        content.appendChild(strNde);
        renderTable(strNde, [item], item.name, 'hd2', 'cl2');
    })

    const footer = document.getElementById('footer');
    footer.className = 'footer'
    if (json.event) {
        footer.innerText = ''
        Object.keys(json.event).forEach(key => {
            let e =  document.createElement('span');
            e.innerText = `${key}: ${json.event[key]}`
            e.className = "event"
            footer.appendChild(e)
        })
    }
};

function div(cssClass) {
    let div =  document.createElement('div');
    div.className = cssClass;
    return div;
}

function renderHeader(value, cssClass) {
    let tbl = div('r-tb ' + cssClass);
    let bdy = div('r-tb-body');
    let row = div('r-tb-row');
    let cell = div('r-tb-cell');
    bdy.appendChild(row);
    row.append(cell);
    cell.innerText = value;
    tbl.appendChild(bdy);
    return tbl;
}

function renderTable(parentNode, values, headerValue, headerCss, cellCss) {
    parentNode.appendChild(renderHeader(headerValue, headerCss))

    const tbl = div('r-tb');
    const bdy = div('r-tb-body');
    tbl.appendChild(bdy);
    parentNode.appendChild(tbl);

    var row = div('r-tb-row');
    var counter = 0;

    values.forEach(item => {
        for (key in item) {
            if (specMap.get(key)) {
                let cell = div('r-tb-cell ' + cellCss);
                if (spec[key].length > 2) {
                    factor = spec[key][2];
                } else {
                    factor = 1;
                }
                cell.innerHTML = `<span>${spec[key][0]}</span><br/><span>${(item[key]*factor).toFixed(1)} ${spec[key][1]}</span>`;
                row.appendChild(cell);
                if (counter == 4) {
                    bdy.appendChild(row);
                    row = div('r-tb-row');
                    counter = 0;
                } else {
                    counter++;
                }
            }
        }
        bdy.appendChild(row);
    });
}
""")

_HTML = const("""
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="/style.css">
    <script src="/script.js"></script>
</head>
<body>
<div id="content">
    DTU started. Waiting for data ....
</div>
<div id="footer"></div>
</body>
</html>
""")


class WebServer:

    dtu_data = {'last': {'time': datetime.now(timezone.utc), 'inverter_name': 'HM600', 'yield_total': 1305799.0, 'temperature': 18.6, 'powerfactor': 1.0, 'yield_today': 207.0, 'phases': [{'frequency': 50.01, 'current': 0.9599999, 'power': 226.3, 'voltage': 236.3}], 'efficiency': 95.49, 'strings': [{'energy_daily': 67, 'name': 'Panel1', 'power': 110.3, 'current': 3.06, 'energy_total': 580076, 'irradiation': 29.026, 'voltage': 36.1}, {'energy_daily': 140, 'name': 'Panel2', 'power': 126.7, 'current': 3.7, 'energy_total': 725723, 'irradiation': 33.342, 'voltage': 34.3}]}}

    def __init__(self, data_provider=None, start_page=None, wifi_mode=network.STA_IF):
        if data_provider is None:
            self.data_provider = self
        else:
            self.data_provider = data_provider
        self.start_page = start_page
        self.wifi_mode = wifi_mode
        self.server = None

    def get_data(self):
        _last = self.dtu_data['last']
        _timestamp = _last['time']
        if isinstance(_timestamp, datetime):
            _new_ts = _timestamp.isoformat().split('.')[0]
            _last['time'] = _new_ts
        return f"{_last}".replace('\'', '\"')

    async def serve_client(self, reader, writer):
        start_time = time.ticks_us()
        request_line = await reader.readline()
        print("Request:", request_line)
        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass

        request = str(request_line)
        if request.find('/data') == 6:
            # print('=> data requested')
            header = 'HTTP/1.1 200 OK\r\nContent-type: application/json\r\n\r\n'
            json = self.data_provider.get_data()
            response = f"{json}"
        elif request.find('/style.css') == 6:
            # print('=> css requested')
            header = 'HTTP/1.1 200 OK\r\nContent-type: text/css\r\n\r\n'
            response = _CSS
        elif request.find('/script.js') == 6:
            # print('=> css requested')
            header = 'HTTP/1.1 200 OK\r\nContent-type: text/javascript\r\n\r\n'
            response = _JS
        elif request.find('/favicon.ico') == 6:
            header = 'HTTP/1.1 200 OK\r\nContent-type: text/html\r\n\r\n'
            response = "n/a"
        else:
            try:  # serve file
                header = 'HTTP/1.1 200 OK\r\nContent-type: text/html\r\n\r\n'
                if self.start_page:
                    print('serving', self.start_page)
                    file = open(self.start_page, "r")
                    response = file.read()
                    file.close()
                else:
                    # print('serving default request')
                    response = _HTML
            except Exception as e:
                header = "HTTP/1.1 404 Not Found\n"
                response = "<html><body><h1>File not found</h1></body></html>"
                print(e)

        writer.write(header)
        writer.write(response)

        print("elapsed time [µs]: ",  time.ticks_us() - start_time)
        await writer.drain()
        await writer.wait_closed()

    async def webserver(self):
        import wlan

        if self.wifi_mode == network.AP_IF:
            wlan.start_ap(ssid='MPY-DTU')
        elif self.wifi_mode == network.STA_IF:
            wlan.do_connect()
        else:
            print("no valid wifi config. skipping webserver")
            return     # no valid wifi!

        ip = network.WLAN(self.wifi_mode).ifconfig()[0]
        port = 80
        url = f'http://{ip}:{port}'

        self.server = await asyncio.start_server(self.serve_client, ip, port)
        #asyncio.create_task()
        print(f'WebServer started: {url}')
        while True:
            try:
                await self.server.wait_closed()
                break
            except AttributeError:
                await asyncio.sleep(0.1)
            await asyncio.sleep(1)  # keep up server

    def start(self):
        try:
            asyncio.run(self.webserver())
        except KeyboardInterrupt:
            self.stop()
        finally:
            asyncio.new_event_loop()

    def stop(self):
        if self.server is not None:
            self.server.close()


if __name__ == '__main__':
    WebServer(start_page="web/index.html").start()
