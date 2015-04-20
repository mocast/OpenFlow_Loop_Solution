#!/usr/bin/env python
# -*- Mode: Python; tab-width: 4; coding: utf8 -*-
#
# Copyright 2015 Silvan Streit
#	 basic structure derived from pox/misc/of_tutorial.py by James McCauley
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
"""
This openflow controller finds the paths between hosts given the topology.
The corresponding flows are pushed to the switches on connection.
This way loops can be taken care of and a loopless graph is created.

For unknown packages, the following behavior can be selected: (mode)

1) "static":		static switch, only use given network graph, 
						other packages are ignored
2) "hub":			simple hub, flood unknown packages
3) "switch":		learning switch with flows pushed to the switch

!! only static can handle networks with loops !!

You can select the mode by specifing --mode=satic at the command line.
Standard mode is static.

The topology so far has to be hard coded and is selected by the command
line via --topology=GoogleWAN

Available topologies:
	GoogleWAN
	circle
	None
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.addresses import EthAddr
import pox.proto.arp_responder as arp

log = core.getLogger()
MODE = "static"
TOPOLOGY = "None"


class switch(object):
	"Represents a controlled switch in a network."

	def __init__(self,dpid):
		"Initialize new switch. Save dpid and initialize lists."
		#swith id
		self.dpid = dpid
		#port:device(object) which are connected in the network
		self.port_to_connected_devices = {}
		#list of flows which will be pushed to the switch on connection
		self.flows = []


	def port_to(self, dpid):
		"Returns the port which connects to the switch with the given dpid."
		for port, device in self.port_to_connected_devices.iteritems():
			if isinstance(device, switch) and device.dpid == dpid:
				return port


	def get_paths(self, network):
		"Recursive function to get the paths between the hosts. (depth first)"
		open_paths = []
		network.checked(self.dpid) #remember the switch to prevent loop-traps
		#loop over all connected devices
		for port, device in self.port_to_connected_devices.iteritems():
			
			#if it's a host -> connect all open_paths to it and start a new one
			if isinstance(device, host):
				for oc in open_paths: #connect all open_paths with the new host
					#they are host-to-host -> save in final list
					network.paths.append(
						oc + [
								(	('s{}'.format(self.dpid),port),
									('h{}'.format(device.hostid),0)  )
							])
					log.debug('Found new path to host @ switch {s}: '\
						'{p}'.
						format(p=(
						oc + [
								(	('s{}'.format(self.dpid),port),
									('h{}'.format(device.hostid),0)  )
							]), s=self.dpid) )
				#create new open_path to the new host
				open_paths.append([(	('h{}'.format(device.hostid),0),
										('s{}'.format(self.dpid),port)  )])
			
			#if it's a switch -> get its paths (depth first)
			elif isinstance(device, switch):
				if not network.already_checked(device.dpid):# loop prevention
					#get the paths of the connected switch (recursive)
					new_open_paths = device.get_paths(network)
					#get the port that connects to us:
					device_port = network.switches[device.dpid].\
										port_to(self.dpid)
					
					for noc in new_open_paths:
						noc.append((
									('s{}'.format(device.dpid),device_port),
									('s{}'.format(self.dpid),port),
								)) #add the last link to the path
						
						# combine all existing ones with it: host-to-host
						for oc in open_paths:
							nc = noc[:] #true copy
							#combine the two (reverse one)
							for link in reversed(oc):
								nc.append( (link[1],link[0]) )
							network.paths.append(nc) # save to final list
							log.debug('Found new path @ switch {s}: '\
								'{p}'.
								format(p=nc, s=self.dpid) )
					#also keep them as open_paths - after all is done!
					open_paths += new_open_paths
			
			else:
				log.warning("Unknown devide type in network @ switch {s}: "\
							"{d} @ {p}".
							format(d=device,p=port,s=self.dpid))
			
		return open_paths
	
	def create_flow (self, match, out_port, buffer_id = None ):
		"""
		Creates Flow which can be installed on a switch
		"""
		flow = of.ofp_flow_mod()
		flow.match = match

		if buffer_id is not None:
			flow.buffer_id = buffer_id

		# Add an action to send to the specified port
		flow.actions.append(of.ofp_action_output(port = out_port))
	
		return flow
	
	def get_flows(self,network):
		"Creates the list of flows for this switch given a network with paths."
		for cn in network.paths:
			for link_id in range(len(cn)):
				#look for this switch in the path
				if cn[link_id][1][0] == "s{}".format(self.dpid):
					## add flows in both directions (for the hosts at each end)
					for match in network.host_by_id(cn[0][0][0]).get_matches():
						self.flows.append( self.create_flow(
											match		= match,
											out_port	= cn[link_id][1][1],
										) )
					for match in network.host_by_id(cn[-1][1][0]).get_matches():
						self.flows.append( self.create_flow(
											match		= match,
											out_port	= cn[link_id+1][0][1],
										) )


	def connect(self, connection):
		"connects this switch-object to a 'real' switch."
		# Keep track of the connection to the switch so that we can
		# send it messages!
		self.connection = connection

		# This binds our PacketIn event listener
		connection.addListeners(self)

		# Use this table to keep track of which ethernet address is on
		# which switch port (keys are MACs, values are ports).
		self.mac_to_port = {}
		
		# push precomputed flows
		for flow in self.flows:
			self.install_flow(flow)


	def resend_packet (self, packet_in, out_port):
		"""
		Instructs the switch to resend a packet that it had sent to us.
		"packet_in" is the ofp_packet_in object the switch had sent to the
		controller due to a table-miss.
		"""
		msg = of.ofp_packet_out()
		msg.data = packet_in

		# Add an action to send to the specified port
		action = of.ofp_action_output(port = out_port)
		msg.actions.append(action)

		# Send message to switch
		self.connection.send(msg)


	def act_like_hub (self, packet, packet_in):
		"Implement hub-like behavior for unknown packages."

		# Flood the packet out everything but the input port (hub-like)
		self.resend_packet(packet_in, of.OFPP_ALL)


	def act_like_switch (self, packet, packet_in):
		"Implement switch-like behavior for unknown packages."

		# Learn the port for the source MAC
		if packet.src not in self.mac_to_port:
			self.mac_to_port[packet.src]=packet_in.in_port
			log.debug('Found new MAC address @ switch {s}: '\
						'{m} @ port {p}'.
						format(m=packet.src, p=packet_in.in_port, s=self.dpid) )
		else:
			if self.mac_to_port[packet.src] != packet_in.in_port:
				log.warning('Port of MAC address changed @ switch {s}: {m} '\
								'was @ port {p_old}, is now @ port {p_new}'.
						format(	m=packet.src,p_old=self.mac_to_port[packet.src],
								p_new=packet_in.in_port, s=self.dpid) )
				self.mac_to_port[packet.src]=packet_in.in_port

		#if the port associated with the destination MAC of the packet is known:
		if packet.dst in self.mac_to_port:

			log.debug('Installing new flow @ switch {s}: '\
						'source: {src} @ port {p_src}, '\
						'destination : {dst} @ port {p_dst}'.
						format(	src=packet.src, p_src=packet_in.in_port, 
								dst=packet.dst,
								p_dst=self.mac_to_port[packet.dst],
								s=self.dpid) )

			# Install the new Flow
			self.install_new_flow(
					match		= of.ofp_match(
							dl_dst	= packet.dst,
							dl_src	= packet.src,
							in_port	= packet_in.in_port,
						),
					out_port	= self.mac_to_port[packet.dst],
					buffer_id	= packet_in.buffer_id, #push buffered package
				)

		else:
			# Flood the packet out everything but the input port (hub-like)
			self.resend_packet(packet_in, of.OFPP_ALL)



	def install_new_flow (self, match, out_port, buffer_id = None):
		"Creates and sends a new flow to switch."
		flow = self.create_flow ( match, out_port, buffer_id)
		self.connection.send(flow)


	def install_flow (self, flow):
		"Sends flow to switch."
		self.connection.send(flow)



	def _handle_PacketIn (self, event):
		"Handles packet in messages from the switch."

		packet = event.parsed # This is the parsed packet data.
		if not packet.parsed:
		  log.warning("Ignoring incomplete packet")
		  return

		packet_in = event.ofp # The actual ofp_packet_in message.

		#select behavior based on mode:
		if MODE == "hub":
			self.act_like_hub(packet, packet_in)
		elif MODE == "switch":
			self.act_like_switch(packet, packet_in)
		elif MODE == "static":
			log.warning('Ingnored package @ switch {s}: '\
						'from {src} @ port {p} to {dst} (port unknown)'.
						format(	src=packet.src, p=packet_in.in_port, 
								dst=packet.dst, s=self.dpid) )


class host(object):
	"Represents a host in a network."
	def __init__(self,hostid):
		"Initialize new host. Save hostid."
		self.hostid = hostid
	def get_matches(self):
		"Returns a list of match-objects for this host."
		return [of.ofp_match(
						dl_dst	= EthAddr("00:00:00:00:00:{:02x}".\
									format(self.hostid)),
					),
#				of.ofp_match(
#						nw_dst	= ("10.0.0.{}".format(self.hostid)),
#						dl_type=0x800,
#					),
				]


class network(object):
	"Represents a network of hosts and switches."
	def __init__(self, switches,hosts,links):
		"Initialize network and find als paths and flows."
		core.openflow.addListeners(self) #attach to the network
		self.switches = switches	#dict of switches:  dpid:switch-object
		self.hosts = hosts			#dict of hosts:   hostid:host-object
		
		# link the switches -> add the links to the ports of the switches
		for li in links:
			for i in range(2):
				if 	(		self.is_device(li[i][0])
						and self.is_device(li[i-1][0])
						and self.is_switch(li[i][0])		):
					self.switch_by_id(li[i][0]).\
						port_to_connected_devices[li[i][1]]\
							= self.device_by_id(li[i-1][0])
		
		self.paths = [] # loopless paths in the network, host-to-host
		#find all paths
		self.get_paths()
		#calculate flows for the switches
		self.get_flows()
		log.info("Custom OpenFlow controller sarted successully.")
		log.debug("The following paths were found int the topology {t}: {p}".
						format(t=TOPOLOGY,p=self.paths))
	
	def is_switch(self,devid):
		"Checks if devid points to an existing switch."
		if isinstance(devid,str):
			if devid[0] =='s':
				devid = int(devid[1:])
			else:
				return False
		if devid in self.switches:
			return True
		else:
			return False
	
	def is_host(self,devid):
		"Checks if devid points to an existing host."
		if isinstance(devid,str):
			if devid[0] =='h':
				devid = int(devid[1:])
			else:
				return False
		if devid in self.hosts:
			return True
		else:
			return False
	
	def is_device(self,devid):
		"Checks if devid points to an existing device in the network."
		if isinstance(devid,str) and devid[0] =='h':
			return  self.is_host(devid)
		else: #asume switch
			return self.is_switch(devid)
	
	def device_by_id(self,devid):
		"Returns the device-object given the devid."
		if devid[0] =='h':
			return self.host_by_id(devid)
		else:
			return self.switch_by_id(devid)
	
	def switch_by_id(self,devid):
		"Returns the switch-object given the devid of a switch."
		if isinstance(devid,str):
			devid = int(devid[1:])
		return self.switches[devid]
	
	def host_by_id(self,devid):
		"Returns the host-object given the devid of a host."
		if isinstance(devid,str):
			devid = int(devid[1:])
		return self.hosts[devid]
	
	def checked(self,dpid):
		"Appends the switch to the list of passed switches (loop prevention)."
		self.passed_switches.append(dpid)
	
	def already_checked(self,dpid):
		"Checks if the switch was already checked (loop prevention)."
		return dpid in self.passed_switches
	
	def get_paths(self):
		"Finds all the paths recursively in the network with loop prevention."
		self.passed_switches = []
		for sw in self.switches.itervalues():
			if not self.already_checked(sw.dpid):
				sw.get_paths(self)
		## correcting paths from back-and-forth loops
		self.paths = [self.shorten_path(cn) for cn in self.paths]
	
	def shorten_path(self,cn):
		"Searches for loops in the given path and removes them."
		used_switches = []
		cuts = set()
		for link in cn:
			if link[1][0] in used_switches:
				c_low = [i for i,x in enumerate(used_switches)\
							if x == link[1][0]][0]
				c_high = len(used_switches)
				for c in range(c_low+1, c_high+1):
					cuts.add(c)
			used_switches.append(link[1][0])
		cn = [link for i,link in enumerate(cn) if i not in cuts]
		return cn
	
	def get_flows(self):
		"Creates the list of flows for all switches."
		for sw in self.switches.itervalues():
			sw.get_flows(self)
	
	def _handle_ConnectionUp(self,event):
		"Catches new connection to a switch and configures it"
		if self.is_switch(event.connection.dpid):
			self.switches[event.connection.dpid].connect(event.connection)
			log.info("Switch {:2} has connected and got configured.".
						format(event.dpid))
		else: #we have a new unknown switch
			self.switches[event.connection.dpid]=switch(event.connection.dpid)
			self.switches[event.connection.dpid].connect(event.connection)
			log.info("New unknown switch {:2} has connected.".
						format(event.dpid))




def launch (mode = "static", topology = "None"):
	"Starts the component to watch for new connected switches and handles ARP."
	#save given settings
	global MODE, TOPOLOGY
	MODE = mode
	TOPOLOGY = topology
	log.info("Starting custom OpenFlow controller with "\
					"mode {m} and topology {t}.".
					format(m=MODE,t=TOPOLOGY))
	## Generate static ARP table
	for i in range(255):
		arp._arp_table[arp.IPAddr("10.0.0.{}".format(i+1))] = arp.Entry(
					"00:00:00:00:00:{:02x}".format(i+1), static=True)
	# launch ARP responder
	arp.launch (	timeout=arp.ARP_TIMEOUT, 
					no_flow=False, 
					eat_packets=True,
					no_learn=False)
	
	## Load the given network
	if TOPOLOGY == "circle":
		#Circle topology (1 loop)
		hosts = {
				1:host( 1),
				2:host( 2),
				3:host( 3),
				4:host( 4),
			}
		switches = {
				1:switch( 1),
				2:switch( 2),
				3:switch( 3),
				4:switch( 4),
			}
		links = [
				(('s1',  1), ('h1',  0)),
				(('s2',  1), ('h2',  0)),
				(('s3',  1), ('h3',  0)),
				(('s4',  1), ('h4',  0)),
				(('s1',  2), ('s2',  2)),
				(('s1',  3), ('s3',  2)),
				(('s2',  3), ('s4',  2)),
				(('s3',  3), ('s4',  3)),
			]
	elif TOPOLOGY == "GoogleWAN":
		#GoogleWAN
		hosts = {
				1:host( 1),
				2:host( 2),
				3:host( 3),
				4:host( 4),
				5:host( 5),
				6:host( 6),
				7:host( 7),
				8:host( 8),
				9:host( 9),
				10:host(10),
				11:host(11),
				12:host(12),
				13:host(13),
				14:host(14),
				15:host(15),
				16:host(16),
				17:host(17),
				18:host(18),
				19:host(19),
				20:host(20),
				21:host(21),
				22:host(22),
				23:host(23),
				24:host(24),
			}
		switches = {
				1:switch( 1),
				2:switch( 2),
				3:switch( 3),
				4:switch( 4),
				5:switch( 5),
				6:switch( 6),
				7:switch( 7),
				8:switch( 8),
				9:switch( 9),
				10:switch(10),
				11:switch(11),
				12:switch(12),
			}
		links = [
				(('s1',  1), ('h1',  0)),
				(('s1',  2), ('h2',  0)),
				(('s1' , 3), ('s2' , 3)),
				(('s1' , 4), ('s3' , 3)),
				(('s2',  1), ('h3',  0)),
				(('s2',  2), ('h4',  0)),
				(('s2' , 4), ('s5' , 3)),
				(('s3',  1), ('h5',  0)),
				(('s3',  2), ('h6',  0)),
				(('s3' , 4), ('s4' , 3)),
				(('s3' , 5), ('s6' , 3)),
				(('s4',  1), ('h7',  0)),
				(('s4',  2), ('h8',  0)),
				(('s4' , 4), ('s5' , 4)),
				(('s4' , 5), ('s7' , 3)),
				(('s4' , 6), ('s8' , 3)),
				(('s5',  1), ('h9',  0)),
				(('s5',  2), ('h10', 0)),
				(('s5' , 5), ('s6' , 4)),
				(('s6',  1), ('h11', 0)),
				(('s6',  2), ('h12', 0)),
				(('s6' , 5), ('s7' , 4)),
				(('s6' , 6), ('s8' , 4)),
				(('s7',  1), ('h13', 0)),
				(('s7',  2), ('h14', 0)),
				(('s7' , 5), ('s8' , 5)),
				(('s7' , 6), ('s11', 3)),
				(('s8',  1), ('h15', 0)),
				(('s8',  2), ('h16', 0)),
				(('s8' , 6), ('s10', 3)),
				(('s9',  1), ('h17', 0)),
				(('s9',  2), ('h18', 0)),
				(('s9' , 3), ('s10', 4)),
				(('s9' , 4), ('s11', 4)),
				(('s10', 1), ('h19', 0)),
				(('s10', 2), ('h20', 0)),
				(('s10', 5), ('s11', 5)),
				(('s10', 6), ('s12', 3)),
				(('s11', 1), ('h21', 0)),
				(('s11', 2), ('h22', 0)),
				(('s11', 6), ('s12', 4)),
				(('s12', 1), ('h23', 0)),
				(('s12', 2), ('h24', 0)),
			]
	else:
		hosts = {}
		switches = {}
		links = []
	
	# enable network (executes network.__init__(switches,hosts,links))
	core.registerNew(network,switches,hosts,links)
