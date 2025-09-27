# OBS Zoom Script for Vtube Studio

### Finds and zooms to VTS model location

https://github.com/user-attachments/assets/e2aa948f-755c-4027-9dfa-5b790baca4b1

## Requirements
* Python 64bit >= 3.10 (3.12.7 recommended)
  * **Python 3.13 is not yet supported by OBS**
  * requires module `websocket-client`
 
## Installation
1. Get **Python** and the required `websocket-client` module. The easiest ways are:
   * Download and unpack the embeddable Python included in this repo. It comes with `websocket-client` so no additional setup is needed.
   * [Install Python](https://www.python.org/downloads/release/python-3127/), then run `python -m pip install websocket-client`
2. Open VTube Studio and enable plugins in the settings:
   <img width="888" height="266" alt="image" src="https://github.com/user-attachments/assets/f0455869-8af5-4ddd-b3e5-77d58be1c2fd" />
3. Open OBS, go to *Tools* -> *Scripts* -> *Python Settings* and find your Python location:
   <img width="844" height="179" alt="image" src="https://github.com/user-attachments/assets/6f6d0287-ffa8-4f65-8cfa-e0b9e444c6b3" />
4. Switch back to *Scripts* tab, and add the zoom script.

## Setup
1. You must grant the script API permission in VTube Studio on first execution:
   <img width="1098" height="874" alt="image" src="https://github.com/user-attachments/assets/0522f4bf-cfbf-412e-8342-121858e960bf" />
   * Sessions after the first one will not require this step unless the access is revoked.
2. Set a hotkey to toggle the zoom in *File* -> *Settings* -> *Hotkeys*:
   <img width="973" height="362" alt="image" src="https://github.com/user-attachments/assets/858129f8-0993-455d-82b3-0d56a16ef31f" />
3. In the *Script* window, set the zoom source. This should be a nested scene containing all the sources you want to be zoomed:
   * Overlays should not be included, as to not make them go off screen while zoomed in
   <img width="414" height="196" alt="image" src="https://github.com/user-attachments/assets/0e8c9a75-ebe0-402c-9fee-35800ace4c2f" />
4. The script is now ready to use, experiment with the rest of the included settings to achieve your desired zoom.



