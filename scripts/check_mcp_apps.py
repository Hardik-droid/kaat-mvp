"""Real local stdio MCP -> shared controller -> Windows tools; opens real apps."""
from pathlib import Path
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def check(output,report):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],
        cwd=str(ROOT),env=dict(os.environ,KAAT_DATA_DIR=str(output/'memory')))
    cases=[('system.open_application',{'application':'notepad'},True),
        ('system.open_application',{'application':'chrome'},True),
        ('system.open_application',{'application':'calculator'},True),
        ('system.open_website',{'url':'https://photos.google.com/'},True),
        ('system.open_folder',{'path':'downloads'},True),
        ('system.get_active_window',{},True),('system.list_installed_apps',{},True),
        ('system.open_application',{'application':'KAAT nonexistent application 192859'},False),
        ('system.open_application',{'application':'cmd.exe /c anything'},False),
        ('system.open_website',{'url':'file:///C:/Windows/System32/calc.exe'},False)]
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            report['available_tools']=[tool.name for tool in (await session.list_tools()).tools]
            for name,args,expected in cases:
                started=time.monotonic()
                response=await session.call_tool(name,args)
                if response.isError:raise RuntimeError('Protocol tool error: '+name)
                data=response.structuredContent
                if data is None:data=json.loads(response.content[0].text)
                passed=(data.get('status')=='success' and data.get('verified') is True) if expected else (
                    data.get('status')=='failed' and data.get('verified') is False)
                row={'tool':name,'arguments':args,'expected_success':expected,'passed':passed,
                    'elapsed_seconds':round(time.monotonic()-started,3),'response':data}
                report['steps'].append(row)
                print(json.dumps(row),flush=True)
                if not passed:raise AssertionError('Unexpected result for '+name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/emergency_mcp_apps')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists() and any(output.iterdir()):parser.error('Choose an empty output directory.')
    output.mkdir(parents=True,exist_ok=True)
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'status':'running','provider_mocks':False,
        'transport':'official MCP Python SDK local stdio','steps':[]}
    try:
        asyncio.run(asyncio.wait_for(check(output,report),timeout=120))
        report['status']='passed'
    except Exception as exc:report.update(status='failed',error=str(exc))
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'steps':len(report['steps']),'report':str(output/'report.json')}))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
