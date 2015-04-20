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
"""Topology which simulates the GoogleWAN with two hosts on each node.

To run this topo use (with remote controller):
sudo mn --custom google-topo.py --topo GoogleWAN --mac --switch ovsk \
		--controller remote
"""

from mininet.topo import Topo

class GoogleWAN(Topo):
	"Googles WAN with two hosts on each node."
	def __init__(	self, 
					datacenters=12, 
					clients=2, 
					datacenterlinks=[
							(1,2),(1,3),
							(2,5),
							(3,4),(3,6),
							(4,5),(4,7),(4,8),
							(5,6),
							(6,7),(6,8),
							(7,8),(7,11),
							(8,10),
							(9,10),(9,11),
							(10,11),(10,12),
							(11,12)
						], 
					**opts):
		# Initialize topology and default options
		Topo.__init__(self, **opts)
		#keep a list of all switches to connect them later
		switches = []
		for d in range(datacenters): # over all switches
			switches.append( self.addSwitch('s%s' % (d + 1)) ) #create switch
			# Python's range(N) generates 0..N-1
			for c in range(clients): #create and connect direct hosts
				host = self.addHost(  "h{n}".format( n=(d*2 + c+1) )  )
				self.addLink(host, switches[d])
		#connect all available datacenters with each other
		for link in datacenterlinks:
			if link[0] <= len(switches) and link[1] <= len(switches):
				self.addLink(switches[link[0]-1], switches[link[1]-1])

# Add the topology to the dictionary of available topologies,
# this allows the parameter '--topo=GoogleWAN' in the command line.
topos = { 'GoogleWAN': ( lambda: GoogleWAN() ) }
