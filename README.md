### This program is still very much a WIP and is currently just a working prototype.

# Scroll Tool

![Example](https://github.com/80sVectorz/scroll_tool/blob/main/images/example.gif?raw=true)

A program that allows you to emulate the scroll wheel with a pointer device.

# Original problem & usage example

I made this program because I couldn't find a good way to rotate the canvas in
Affinity Photo when using a drawing tablet.
At first, the goal for my tool was to just be for rotating the canvas.
But I pivoted to making it a general scroll wheel emulation.

# Disclaimer
**Scroll Tool only supports windows.**

# Installation
Download the latest EXE from [releases](https://github.com/80sVectorz/scroll_tool/releases) and store it somewhere  
You'll need to configure the execution logic yourself. One example is having it launch when pressing on of the function buttons on a Wacom tablet.

# Future plans
Things I already plan to implement are: 
- `.toml` configuration file support so you can customize colors dimensions, sensitivity, etc.
- A user-friendly tool to generate configs for people who'd rather not edit a `.toml` file (This'll have a lower priority)
