#!/usr/bin/env python
# -*- Mode: Python; tab-width: 4; coding: utf8 -*-
#
# Copyright 2015 Silvan Streit
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#	 http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Circle Topology to test loop handling.

Four circular connected switches witch each one host.
!!! The controller has to support loops !!! - this is to test this

                      host(2)
                        |
                     switch(2)
                     /       \
                    /         \
   host(1) -- switch(1)     switch(4) -- host(4)
                    \         /
                     \       /
                     switch(3)
                        |
                      host(3)

To run this topology use (with remote controller):
sudo mn --custom circle-topo.py --topo circle --mac --switch ovsk \
		--controller remote
"""

from mininet.topo import Topo

class Circle( Topo ):
    "Circle Topology to test loop handling."

    def __init__( self, **opts ):
        "Create Circle Topology."

        # Initialize topology
        Topo.__init__( self, **opts )

        # Add hosts and switches
        leftHost = self.addHost( 'h1' )
        topHost = self.addHost( 'h2' )
        bottomHost = self.addHost( 'h3' )
        rightHost = self.addHost( 'h4' )
        leftSwitch = self.addSwitch( 's1' )
        topSwitch = self.addSwitch( 's2' )
        bottomSwitch = self.addSwitch( 's3' )
        rightSwitch = self.addSwitch( 's4' )

        # Add links
        self.addLink( leftHost, leftSwitch )
        self.addLink( topHost, topSwitch )
        self.addLink( bottomHost, bottomSwitch )
        self.addLink( rightSwitch, rightHost )
        self.addLink( leftSwitch, topSwitch )
        self.addLink( leftSwitch, bottomSwitch )
        self.addLink( topSwitch, rightSwitch )
        self.addLink( bottomSwitch, rightSwitch )

# Add the topology to the dictionary of available topologies,
# this allows the parameter '--topo=circle' in the command line.
topos = { 'circle': ( lambda: Circle() ) }
