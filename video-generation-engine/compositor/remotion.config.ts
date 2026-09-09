import { Config } from "@remotion/cli/config";

// Alpha output for compositing over the existing render.
Config.setVideoImageFormat("png");
Config.setPixelFormat("yuva444p10le");
Config.setCodec("prores");
Config.setProResProfile("4444");
