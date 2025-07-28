#!/bin/sh
systemctl reload nginx ; systemctl restart wayfinding ; sleep 2 ; systemctl status wayfinding
