"""Change whole-display orientation through the running WM, without reloading PL."""
import argparse
import json
from bosio_wm_client import BosioWMClient

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rotation',type=int,choices=(0,90,180,270),default=0)
    parser.add_argument('--flip-x',action='store_true')
    parser.add_argument('--flip-y',action='store_true')
    parser.add_argument('--status',action='store_true',help='Read current state without changing it')
    args=parser.parse_args()
    with BosioWMClient('display-settings') as client:
        if args.status:
            result=client.get_state()['output'].get('display_transform',{'supported':False})
        else:
            result=client.set_display_transform(args.rotation,args.flip_x,args.flip_y)
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
