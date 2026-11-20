"""Verify a decoded MP4 against its intended orientation and final hold."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess


def inspect(ffmpeg,path,orientation,frames,hold,preview):
    width,height={"portrait":(1080,1920),"landscape":(1920,1080)}[orientation]
    fps=10 if preview else 30
    if preview:
        width,height=width//4,height//4
        frames,hold=(frames+2)//3,hold//3
    result=subprocess.run([ffmpeg,"-hide_banner","-nostdin","-i",str(path),"-map","0:v:0",
                           "-vf","scale=32:32,format=gray","-f","rawvideo","-pix_fmt","gray","-"],
                          capture_output=True,check=True)
    expected=frames*1024
    if len(result.stdout)!=expected:
        raise ValueError(f"{path}: decoded {len(result.stdout)//1024} frames, expected {frames}")
    stream=next(line for line in result.stderr.decode(errors="replace").splitlines()
                if "Stream #" in line and "Video:" in line)
    if f"{width}x{height}" not in stream or f" {fps} fps" not in stream:
        raise ValueError(f"{path}: wrong frame size or rate: {stream}")
    if hold<=0 or hold>frames:
        raise ValueError("Invalid hold length")
    first=result.stdout[-hold*1024:-(hold-1)*1024] if hold>1 else result.stdout[-1024:]
    for offset in range(expected-hold*1024,expected,1024):
        current=result.stdout[offset:offset+1024]
        # Permit minor codec variation on a stationary image.
        if sum(abs(a-b) for a,b in zip(first,current))/1024>1.5:
            raise ValueError(f"{path}: final {hold} frames do not hold")
    return {"file":path.name,"orientation":orientation,"width":width,"height":height,"fps":fps,
            "frames":frames,"duration_seconds":float(Fraction(frames,fps)),"verified_hold_frames":hold,
            "review":"preview" if preview else "clean"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",type=Path)
    parser.add_argument("--ffmpeg",default="ffmpeg")
    parser.add_argument("--orientation",choices=("portrait","landscape"),required=True)
    parser.add_argument("--frames",type=int,required=True)
    parser.add_argument("--hold",type=int,default=150)
    parser.add_argument("--preview",action="store_true")
    args=parser.parse_args()
    print(json.dumps(inspect(args.ffmpeg,args.file,args.orientation,args.frames,args.hold,args.preview)))


if __name__=="__main__":
    main()
