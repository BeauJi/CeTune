# -*- coding: utf-8 -*
import os,sys
import argparse
lib_path = os.path.abspath(os.path.join('..'))
sys.path.append(lib_path)
import common as cn
import os, sys
import time
import pprint
import re
import yaml
from collections import OrderedDict
import json
import numpy
import copy
import config
from multiprocessing import Process, Lock, Queue
import multiprocessing
import threading
import csv
import io,logging,traceback

pp = pprint.PrettyPrinter(indent=4)
class Analyzer:
    def __init__(self, dest_dir,name):
        self.common = cn
        self.common.cetune_log_file = name+"-cetune_process.log"
        self.common.cetune_error_file = name+"-cetune_error.log"
        self.common.cetune_console_file= name+"-cetune_console.log"

        self.dest_dir = dest_dir
        self.cluster = {}
        self.cluster["dest_dir"] = dest_dir
        self.cluster["dest_conf_dir"] = dest_dir
        self.cluster["dest_dir_root"] = dest_dir
        self.all_conf_data = config.Config("all.conf") 
        self.cluster["user"] = self.all_conf_data.get("user")
        self.cluster["head"] = self.all_conf_data.get("head")
        self.cluster["diskformat"] = self.all_conf_data.get("disk_format", dotry=True)
        self.cluster["client"] = self.all_conf_data.get_list("list_client")
        self.cluster["osds"] = self.all_conf_data.get_list("list_server")
        self.cluster["mons"] = self.all_conf_data.get_list("list_mon")
        self.cluster["rgw"] = self.all_conf_data.get_list("rgw_server")
        self.cluster["vclient"] = self.all_conf_data.get_list("list_vclient")
        self.cluster["head"] = self.all_conf_data.get("head")
        self.cluster["user"] = self.all_conf_data.get("user")
        self.cluster["monitor_interval"] = self.all_conf_data.get("monitoring_interval")
        self.cluster["osd_daemon_num"] = 0
        self.cluster["perfcounter_data_type"] = self.all_conf_data.get_list("perfcounter_data_type")
        self.cluster["perfcounter_time_precision_level"] = self.all_conf_data.get("perfcounter_time_precision_level")
        self.cluster["distributed"] = self.all_conf_data.get("distributed_data_process")
        self.cluster["tmp_dir"] =self.all_conf_data.get("tmp_dir")
        self.result = OrderedDict()
        self.result["workload"] = OrderedDict()
        self.result["ceph"] = OrderedDict()
        self.result["rgw"] = OrderedDict()
        self.result["client"] = OrderedDict()
        self.result["vclient"] = OrderedDict()
        self.get_validate_runtime()
        self.result["runtime"] = int(float(self.validate_time))
        self.result["status"] = self.getStatus()
        self.result["description"] = self.getDescription()

        self.whoami = name
        self.workpool = WorkPool( self.common )


    def collect_node_ceph_version(self,dest_dir):
        node_list = []
        node_list.extend(self.cluster["osds"])
        node_list.append(self.cluster["head"])
        version_list = {}
        for node in node_list:
            if os.path.exists(os.path.join(dest_dir,node,node+'_ceph_version.txt')):
                data = open(os.path.join(dest_dir,node,node+'_ceph_version.txt'),'r')
                if data:
                    version_list[node] = data.read().strip('\n')
                else:
                    version_list[node] = 'None'
            else:
                version_list[node] = 'None'
        return version_list

    def test_write_json(self,data,file):
        json.dump(data,open(file,'w'))

    def process_data(self):
        process_list = []
        user = self.cluster["user"]
        dest_dir = self.cluster["dest_dir"]
        session_name = self.cluster["dest_dir_root"].split('/')
        if session_name[-1] != '':
            self.result["session_name"] = session_name[-1]
        else:
            self.result["session_name"] = session_name[-2]

        if self.whoami in self.cluster["osds"]:
            self.result["ceph"][self.whoami]={}
            system, workload = self._process_data()
            self.result["ceph"][self.whoami] = system
            self.result["ceph"].update(workload)
        if self.whoami in self.cluster["rgw"]:
            self.result["rgw"][self.whoami]={}
            system, workload = self._process_data()
            self.result["rgw"][self.whoami] = system
            self.result["rgw"].update(workload)
        if self.whoami in self.cluster["client"]:
            self.result["client"][self.whoami]={}
            system, workload = self._process_data()
            self.result["client"][self.whoami] = system
            self.result["client"].update(workload)
        if self.whoami in self.cluster["vclient"]:
            params = self.result["session_name"].split('-')
            self.cluster["vclient_disk"] = ["/dev/%s" % params[-1]]
            self.result["vclient"][self.whoami]={}
            system, workload = self._process_data()
            self.result["vclient"][self.whoami] = system
            self.result["vclient"].update(workload)
        return

    def get_execute_time(self):
        dest_dir = self.dest_dir
        cf = config.Config(dest_dir+"/conf/all.conf")
        head = ''
        head = cf.get("head")
        file_path = os.path.join(dest_dir,"raw",head,head+"_process_log.txt")
        if head != '':
            if os.path.exists(os.path.join(dest_dir,"raw",head)):
                for file_path in os.listdir(os.path.join(dest_dir,"raw",head)):
                    if file_path.endswith("_process_log.txt"):
                        with open("%s/%s" % (os.path.join(dest_dir,"raw",head),file_path), "r") as f:
                            lines = f.readlines()
                if len(lines) != 0 and lines != None:
                    str_time = ''
                    try:
                        str_time = lines[0].replace('CST ','')
                        str_time = str_time.replace('\n','')
                        str_time = time.strftime("%Y-%m-%d %H:%M:%S",time.strptime(str_time))
                    except:
                        pass
                    return str_time
            else:
                return ''

    def summary_result(self, data):
        # generate summary
        benchmark_tool = ["fio", "cosbench", "vdbench"]
        data["summary"]["run_id"] = {}
        res = re.search('^(\d+)-(\w+)-(\w+)-(\w+)-(\w+)-(\w+)-(\w+)-(\d+)-(\d+)-(\w+)$',data["session_name"])
        if not res:
            self.common.printout("ERROR", "Unable to get result infomation")
            return data
        data["summary"]["run_id"][res.group(1)] = OrderedDict()
        tmp_data = data["summary"]["run_id"][res.group(1)]
        tmp_data["Timestamp"] = self.get_execute_time()
        tmp_data["Status"] = data["status"]
        tmp_data["Description"] = data["description"]
        tmp_data["Op_size"] = res.group(5)
        tmp_data["Op_Type"] = res.group(4)
        tmp_data["QD"] = res.group(6)
        tmp_data["Driver"] = res.group(3)
        tmp_data["SN_Number"] = 0
        tmp_data["CN_Number"] = 0
        tmp_data["Worker"] = res.group(2)
        if data["runtime"] == 0:
            data["runtime"] = int(res.group(9))
        tmp_data["Runtime"] = "%d" % (data["runtime"])
        tmp_data["IOPS"] = 0
        tmp_data["BW(MB/s)"] = 0
        tmp_data["Latency(ms)"] = 0
        tmp_data["SN_IOPS"] = 0
        tmp_data["SN_BW(MB/s)"] = 0
        tmp_data["SN_Latency(ms)"] = 0
        rbd_count = 0
        osd_node_count = 0
        try:
            read_IOPS = 0
            read_BW = 0
            read_Latency = 0
            write_IOPS = 0
            write_BW = 0
            write_Latency = 0
            for engine_candidate in data["workload"].keys():
                if engine_candidate in benchmark_tool:
                    engine = engine_candidate
            for node, node_data in data["workload"][engine].items():
                rbd_count += 1
                read_IOPS += float(node_data["read_iops"])
                read_BW += float(node_data["read_bw"])
                read_Latency += float(node_data["read_lat"])
                write_IOPS += float(node_data["write_iops"])
                write_BW += float(node_data["write_bw"])
                write_Latency += float(node_data["write_lat"])
            if tmp_data["Op_Type"] in ["randread", "seqread", "read"]:
                tmp_data["IOPS"] = "%.3f" % read_IOPS
                tmp_data["BW(MB/s)"] = "%.3f" % read_BW
                if rbd_count > 0:
                    tmp_data["Latency(ms)"] = "%.3f" % (read_Latency/rbd_count)
            elif tmp_data["Op_Type"] in ["randwrite", "seqwrite", "write"]:
                tmp_data["IOPS"] = "%.3f" % write_IOPS
                tmp_data["BW(MB/s)"] = "%.3f" % write_BW
                if rbd_count > 0:
                    tmp_data["Latency(ms)"] = "%.3f" % (write_Latency/rbd_count)
            elif tmp_data["Op_Type"] in ["randrw", "rw", "readwrite"]:
                tmp_data["IOPS"] = "%.3f, %.3f" % (read_IOPS, write_IOPS)
                tmp_data["BW(MB/s)"] = "%.3f, %.3f" % (read_BW, write_BW)
                if rbd_count > 0:
                    tmp_data["Latency(ms)"] = "%.3f, %.3f" % ((read_Latency/rbd_count), (write_Latency/rbd_count))
        except:
            pass
        read_SN_IOPS = 0
        read_SN_BW = 0
        read_SN_Latency = 0
        write_SN_IOPS = 0
        write_SN_BW = 0
        write_SN_Latency = 0
        diskformat = self.common.parse_disk_format( self.cluster['diskformat'] )
        if len(diskformat):
            typename = diskformat[0]
        else:
            typename = "osd"
        for node, node_data in data["ceph"][typename]["summary"].items():
            osd_node_count += 1
            read_SN_IOPS += numpy.mean(node_data["r/s"])*int(node_data["disk_num"])
            read_SN_BW += numpy.mean(node_data["rMB/s"])*int(node_data["disk_num"])
            lat_name = "r_await"
            if lat_name not in node_data:
                lat_name = "await"
            read_SN_Latency += numpy.mean(node_data[lat_name])
            write_SN_IOPS += numpy.mean(node_data["w/s"])*int(node_data["disk_num"])
            write_SN_BW += numpy.mean(node_data["wMB/s"])*int(node_data["disk_num"])
            lat_name = "w_await"
            if lat_name not in node_data:
                lat_name = "await"
            write_SN_Latency += numpy.mean(node_data[lat_name])

        if tmp_data["Op_Type"] in ["randread", "seqread", "read"]:
            tmp_data["SN_IOPS"] = "%.3f" % read_SN_IOPS
            tmp_data["SN_BW(MB/s)"] = "%.3f" % read_SN_BW
            if osd_node_count > 0:
                tmp_data["SN_Latency(ms)"] = "%.3f" % (read_SN_Latency/osd_node_count)
        elif tmp_data["Op_Type"] in ["randwrite", "seqwrite", "write"]:
            tmp_data["SN_IOPS"] = "%.3f" % write_SN_IOPS
            tmp_data["SN_BW(MB/s)"] = "%.3f" % write_SN_BW
            if osd_node_count > 0:
                tmp_data["SN_Latency(ms)"] = "%.3f" % (write_SN_Latency/osd_node_count)
        elif tmp_data["Op_Type"] in ["randrw", "readwrite", "rw"]:
            tmp_data["SN_IOPS"] = "%.3f, %.3f" % (read_SN_IOPS, write_SN_IOPS)
            tmp_data["SN_BW(MB/s)"] = "%.3f, %.3f" % (read_SN_BW, write_SN_BW)
            if osd_node_count > 0:
                tmp_data["SN_Latency(ms)"] = "%.3f, %.3f" % (read_SN_Latency/osd_node_count, write_SN_Latency/osd_node_count)

        tmp_data["SN_Number"] = osd_node_count
        try:
            tmp_data["CN_Number"] = len(data["client"]["cpu"])
        except:
            tmp_data["CN_Number"] = 0
        return data

    def _process_data(self):
        result = {}
        fio_log_res = {}
        workload_result = {}
        dest_dir = self.cluster["dest_dir"]
        node_name = self.whoami
        self.common.printout("LOG","dest_dir:%s"%dest_dir)
        self.workpool.set_return_data_set( fio_log_res, workload_result, result)
        for dir_name in os.listdir("%s/%s/" % (dest_dir, node_name)):
            if 'smartinfo.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_smartinfo_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name))
            if 'cosbench' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_cosbench_data,  "%s/%s/%s" %(dest_dir, node_name, dir_name), dir_name)
            if '_sar.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_sar_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name))
            if 'totals.html' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_vdbench_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name), node_name)
            if '_fio.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_fio_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name), dir_name)
            if '_fio_iops.1.log' in dir_name or '_fio_bw.1.log' in dir_name or '_fio_lat.1.log' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                if "_fio_iops.1.log" in dir_name:
                    volume = dir_name.replace("_fio_iops.1.log", "")
                if "_fio_bw.1.log" in dir_name:
                    volume = dir_name.replace("_fio_bw.1.log", "")
                if "_fio_lat.1.log" in dir_name:
                    volume = dir_name.replace("_fio_lat.1.log", "")
                self.workpool.schedule( self.process_fiolog_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name), volume )
            if '_iostat.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_iostat_data,  node_name, "%s/%s/%s" % (dest_dir, node_name, dir_name))
            if '_interrupts_end.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                if os.path.exists("%s/%s" % (dest_dir,  dir_name.replace('end','start'))):
                    interrupt_end = "%s/%s" % (dest_dir,  dir_name)
                    interrupt_start   = "%s/%s" % (dest_dir,  dir_name.replace('end','start'))
                    self.interrupt_diff(dest_dir,self.whoami,interrupt_start,interrupt_end)
            if '_process_log.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_log_data,  "%s/%s/%s" % (dest_dir, node_name, dir_name) )
            if '.asok.txt' in dir_name:
                self.common.printout("LOG","Processing %s_%s" % (self.whoami, dir_name))
                self.workpool.schedule( self.process_perfcounter_data,  dir_name, "%s/%s/%s" % (dest_dir, node_name, dir_name) )
#                try:
#                    res = self.process_perfcounter_data("%s/%s/%s" % (dest_dir, node_name, dir_name))
#                    for key, value in res.items():
#                        if dir_name not in workload_result:
#                            workload_result[dir_name] = OrderedDict()
#                        workload_result[dir_name][key] = value
#                except:
#                    pass
        self.workpool.wait_all()
        self.test_write_json(result,"%s/%s" % (node_name, self.whoami+"-system.json"))
        self.test_write_json(workload_result,"%s/%s" % (node_name, self.whoami+"-workload.json"))
        return [result, workload_result]

    def process_smartinfo_data(self, path):
        output = {}
        with open(path, 'r') as f:
            tmp = f.read()
        output.update(json.loads(tmp, object_pairs_hook=OrderedDict))
        self.workpool.enqueue_data( ["process_smartinfo_data", output] )
        return output

    def interrupt_diff(self,dest_dir,node_name,s_path,e_path):
        s_p = s_path
        e_p = e_path
        result_name = node_name+'_interrupt.csv'
        result_path_node = os.path.join(dest_dir,result_name)
        s_l = []
        e_l = []
        diff_list = []
        with open(s_p, 'r') as f:
            s = f.readlines()
        with open(e_p, 'r') as f:
            e = f.readlines()
        for i in s:
            tmp = []
            tmp = i.split(' ')
            while '' in tmp:
                tmp.remove('')
            s_l.append(tmp)
        for i in e:
            tmp = []
            tmp = i.split(' ')
            while '' in tmp:
                tmp.remove('')
            e_l.append(tmp)
        if self.check_interrupt(s_l,e_l):
            for i in range(len(s_l)):
                lines = []
                for j in range(len(s_l[i])):
                    if s_l[i][j].isdigit() and e_l[i][j].isdigit():
                        lines.append(int(e_l[i][j]) - int(s_l[i][j]))
                    else:
                        lines.append(e_l[i][j])
                diff_list.append(lines)
            ##write interrupt to node and conf
            self.common.printout("LOG","write interrput to node and conf.")
            if os.path.exists(result_path_node):
                os.remove(result_path_node)
            output_node = file(result_path_node,'wb')
            interrupt_csv_node = csv.writer(output_node)
            if len(diff_list) != 0:
                diff_list[0][0] = ""
                interrupt_csv_node.writerow(diff_list[0])
                del diff_list[0]
                new_diff_list = self.delete_colon(diff_list)
                for i in new_diff_list:
                    interrupt_csv_node.writerows([i])
                output_node.close()
            else:
                self.common.printout("WARNING","no interrupt.")
        else:
            self.common.printout("ERROR",'interrupt_start lines and interrupt_end lines are different ! can not calculate different value!')

    def delete_colon(self,data_list):
        self.d_list = data_list
        for i in range(len(self.d_list)):
            self.d_list[i][0] = self.d_list[i][0].replace(":","")
            self.d_list[i][-1] = self.d_list[i][-1].strip("\n")
        return self.d_list

    def check_interrupt(self,s_inter,e_inter):
        result = "True"
        if len(s_inter)!=len(e_inter):
            result = "False"
        else:
            for i in range(len(s_inter)):
                if len(s_inter[i])!=len(e_inter[i]):
                    result = "False"
        return result

    def process_log_data(self, path):
        result = {}
        try:
            result["phase"] = {}
            with open( path, 'r') as f:
                lines = f.readlines()
    
            benchmark_tool = ["fio", "cosbench"]
            tmp = {}
            benchmark = {}
    
            for line in lines:
                try:
                    time, tool, status = line.split()
                except:
                    continue
                if tool not in tmp:
                   tmp[tool] = {}
                if tool in benchmark_tool:
                    benchmark[status] = time
                else:
                    tmp[tool][status] = time
    
            for tool in tmp:
                result["phase"][tool] = {}
                result["phase"][tool]["start"] = 0
                try:
                    result["phase"][tool]["stop"] = int(tmp[tool]["stop"]) - int(tmp[tool]["start"])
                except:
                    result["phase"][tool]["stop"] = None
                try:
                    result["phase"][tool]["benchmark_start"] = int(benchmark["start"]) - int(tmp[tool]["start"])
                    if result["phase"][tool]["benchmark_start"] < 0:
                        result["phase"][tool]["benchmark_start"] = 0
                except:
                    result["phase"][tool]["benchmark_start"] = None
                try:
                    result["phase"][tool]["benchmark_stop"] = int(benchmark["stop"]) - int(tmp[tool]["start"])
                    if result["phase"][tool]["benchmark_stop"] < 0:
                        result["phase"][tool]["benchmark_stop"] = 0
                except:
                    result["phase"][tool]["benchmark_stop"] = None
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_log_data", result])
        return result

    def process_cosbench_data(self, path, dirname):
        result = {}
        try:
            result["cosbench"] = OrderedDict()
            result["cosbench"]["cosbench"] = OrderedDict([("read_lat",0), ("read_bw",0), ("read_iops",0), ("write_lat",0), ("write_bw",0), ("write_iops",0), ("lat_unit",'msec'), ('runtime_unit','sec'), ('bw_unit','MB/s')])
            tmp = result
            keys = self.common.bash("head -n 1 %s/%s.csv" %(path, dirname))
            keys = keys.split(',')
            values = self.common.bash('tail -n 1 %s/%s.csv' %(path, dirname) )
            values = values.split(',')
            size = len(keys)
            for i in range(size):
                tmp[keys[i]] = {}
                tmp[keys[i]]["detail"] = {}
                tmp[keys[i]]["detail"]["value"] = values[i]
            tmp = result["cosbench"]["cosbench"]
            io_pattern = result["Op-Type"]["detail"]["value"]
            tmp["%s_lat" % io_pattern] = result["Avg-ResTime"]["detail"]["value"]
            tmp["%s_bw" % io_pattern] = self.common.size_to_Kbytes('%s%s' % (result["Bandwidth"]["detail"]["value"], 'B'), 'MB')
            tmp["%s_iops" % io_pattern] = result["Throughput"]["detail"]["value"]
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_cosbench_data", result ])
        return result

    def get_validate_runtime(self):
        self.validate_time = 0
        dest_dir = self.cluster["dest_dir"]
        stdout = self.common.bash('grep " runt=.*" -r %s' % (dest_dir))
        fio_runtime_list = re.findall('runt=\s*(\d+\wsec)', stdout)
        for fio_runtime in fio_runtime_list:
            validate_time = self.common.time_to_sec(fio_runtime, 'sec')
            if validate_time < self.validate_time or self.validate_time == 0:
                self.validate_time = validate_time

    def getStatus(self):
        self.validate_time = 0
        dest_dir = self.cluster["dest_conf_dir"]
        status = "Unknown"
        try:
            with open("%s/status" % dest_dir, 'r') as f:
                status = f.readline()
        except:
            pass
        return status

    def getParameters(self):
        dest_dir = self.cluster["dest_conf_dir"]
        ps = ""
        try:
            with open("%s/vdbench_params.txt" % dest_dir.replace("raw","conf"), 'r') as f:
                ps = f.read()
        except:
            pass
        return ps

    def getDescription(self):
        dest_dir = self.cluster["dest_conf_dir"]
        desc = ""
        try:
            with open("%s/description" % dest_dir, 'r') as f:
                desc = f.readline()
        except:
            pass
        return desc

    def process_fiolog_data(self, path, volume_name):
        result = {}
        try:
            if "fio_iops" in path:
                result["iops"] = []
                res = result["iops"]
            if "fio_bw" in path:
                result["bw"] = []
                res = result["bw"]
            if "fio_lat" in path:
                result["lat"] = []
                res = result["lat"]
    
            time_shift = 1000
            with open( path, "r" ) as f:
                cur_sec = -1
                self.tmp_res = []
                if 'iops' in path:
                    self.iops_value = 0
                    for line in f.readlines():
                        data = line.split(",")
                        value = int(data[1])
                        timestamp_sec = int(data[0])/time_shift
                        if timestamp_sec > cur_sec:
                            if cur_sec >= 0:
                                self.tmp_res.append( self.iops_value )
                                self.iops_value = 0
                            cur_sec = timestamp_sec
                        self.iops_value += value
                    if len(self.tmp_res) != 0:
                        res.extend(self.tmp_res)
                else:
                    for line in f.readlines():
                        data = line.split(",")
                        timestamp_sec = int(data[0])/time_shift
                        value = int(data[1])
                        if timestamp_sec > cur_sec:
                            if cur_sec >= 0:
                                res.append(numpy.mean(self.tmp_res))
                            cur_sec = timestamp_sec
                        self.tmp_res.append( value )
                    if len(self.tmp_res) != 0:
                        res.append(numpy.mean(self.tmp_res))
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_fiolog_data", volume_name, result])
        return result


    def process_sar_data(self, path):
        result = {}
        try:
            #1. cpu
            f = open(path,'r')
            first_line = f.next().strip('\n')
            f.close()
            node_name = re.findall(r"\((.*?)\)",first_line)[0]
            cpu_num = re.findall(r"\((.*?)\)",first_line)[1][0]
            cpu_core_dict = OrderedDict()
            for line in range(int(cpu_num)+1):
                if line == 0:
                    stdout = self.common.bash( "grep ' *CPU *%' -m 1 "+path+" | awk -F\"CPU\" '{print $2}'; cat "+path+" | grep ' *CPU *%' -A "+str(int(cpu_num)+1)+" | awk '{flag=0;if(NF<=3)next;for(i=1;i<=NF;i++){if(flag==1){printf $i\"\"FS}if($i==\"all\")flag=1};if(flag==1)print \"\"}'" )
                else:
                    stdout = self.common.bash( "grep ' *CPU *%' -m 1 "+path+" | awk -F\"CPU\" '{print $2}'; cat "+path+" | grep ' *CPU *%' -A "+str(int(cpu_num)+1)+" | awk '{flag=0;if(NF<=3)next;for(i=1;i<=NF;i++){if(flag==1){printf $i\"\"FS}if($i==\""+str(line-1)+"\")flag=1};if(flag==1)print \"\"}'" )
                if line ==0:
                    cpu_core_dict[node_name+"_cpu_all"] = stdout
                else:
                    cpu_core_dict[node_name+"_cpu_"+str(line-1)] = stdout
            cpu_core_dict_new = self.common.format_detail_data_to_list(cpu_core_dict)
            result["cpu"] = cpu_core_dict_new
    
            #2. memory
            stdout = self.common.bash("grep 'kbmemfree' -m 1 "+path+" | awk -Fkbmemfree '{printf \"kbmenfree  \";print $2}'; grep \"kbmemfree\" -A 1 "+path+" | awk 'BEGIN{find=0;}    {for(i=1;i<=NF;i++){if($i==\"kbmemfree\"){find=i;next;}}if(find!=0){for(j=find;j<=NF;j++)printf $j\"\"FS;find=0;print \"\"}}'")
            result["memory"] = self.common.convert_table_to_2Dlist(stdout)
    
            #3. nic
            stdout = self.common.bash( "cat "+path+" | awk 'BEGIN{find=0;}{if(find==0){for(i=1;i<=NF;i++){if($i==\"IFACE\"){j=i+1;if($j==\"rxpck/s\"){find=1;lines=1;next}}}};if($j==\"rxerr/s\"){find=2;for(k=1;k<=lines;k++)printf res_arr[k]\"\"FS;}if(find==1){res_arr[lines]=$(j-1);lines=lines+1;}if(find==2)exit}'" )
            nic_array = stdout.split();
            result["nic"] = {}
            for nic_id in nic_array:
                stdout = self.common.bash( "grep 'IFACE' -m 1 "+path+" | awk -FIFACE '{print $2}'; cat "+path+" | awk 'BEGIN{find= 0;}{if(find==0){for(i=1;i<=NF;i++){if($i==\"IFACE\"){j=i+1;if($j==\"rxpck/s\"){find=1;next;}}}}if(find==1&&$j==\"rxerr/s\"){find=0;next}if(find==1 && $(j-1)==\""+nic_id+"\"){for(k=j;k<=NF;k++) printf $k\"\"FS; print \"\"}}'" )
                result["nic"][nic_id] = self.common.convert_table_to_2Dlist(stdout)
    
            for tab in result.keys():
                summary_data_dict = OrderedDict()
                detail_data_dict = OrderedDict()
                total_data_dict = OrderedDict()
                if tab == "cpu":
                    for key, value in result["cpu"].items():
                        if 'all' in key:
                            for summary_node, summary_data in value.items():
                                summary_data_dict[summary_node] = summary_data
                        detail_data_dict[key] = value
                else:
                    summary_data_dict = result[tab]
                total_data_dict["summary"] = summary_data_dict
                total_data_dict["detail"] = detail_data_dict
                result[tab] = total_data_dict
    
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_sar_data", result])
        return result

    def process_iostat_data(self, node, path):
        result = {}
        try:
            output_list = []
            dict_diskformat = {}
            if node in self.cluster["osds"]:
                output_list = self.common.parse_disk_format( self.cluster['diskformat'] )
                for i in range(len(output_list)):
                    disk_list=[]
                    for osd_journal in self.common.get_list(self.all_conf_data.get_list(node)): 
                       tmp_dev_name = osd_journal[i].split('/')[2]
                       if 'nvme' in tmp_dev_name:
                           tmp_dev_name = self.common.parse_nvme( tmp_dev_name )
                       if tmp_dev_name not in disk_list:
                           disk_list.append( tmp_dev_name )
                    dict_diskformat[output_list[i]]=disk_list
            elif node in self.cluster["vclient"]:
                vdisk_list = []
                for disk in self.cluster["vclient_disk"]:
                    vdisk_list.append( disk.split('/')[2] )
                output_list = ["vdisk"]
            if node in self.cluster["client"]:
                cdisk_list = []
                for disk_name in self.all_conf_data.get_list(node):
                    cdisk_list.append( disk_name.split('/')[2] )
                output_list = ["client_disk"]
            # get total second
            runtime = self.common.bash("grep 'Device' "+path+" | wc -l ").strip()
            for output in output_list:
                if output == "client_disk":
                    disk_list = " ".join(cdisk_list)
                    disk_num = len(cdisk_list)
                elif output == "vdisk":
                    disk_list = " ".join(vdisk_list)
                    disk_num = len(vdisk_list)
                else: #osd
                    disk_list = " ".join(dict_diskformat[output])
                    disk_num = len(list(set(dict_diskformat[output])))
                stdout = self.common.bash( "grep 'Device' -m 1 "+path+" | awk -F\"Device:\" '{print $2}'; cat "+path+" | awk -v dev=\""+disk_list+"\" -v line="+runtime+" 'BEGIN{split(dev,dev_arr,\" \");dev_count=0;for(k in dev_arr){count[k]=0;dev_count+=1};for(i=1;i<=line;i++)for(j=1;j<=NF;j++){res_arr[i,j]=0}}{for(k in dev_arr)if(dev_arr[k]==$1){cur_line=count[k];for(j=2;j<=NF;j++){res_arr[cur_line,j]+=$j;}count[k]+=1;col=NF}}END{for(i=1;i<=line;i++){for(j=2;j<=col;j++)printf (res_arr[i,j]/dev_count)\"\"FS; print \"\"}}'")
                result[output] = self.common.convert_table_to_2Dlist(stdout)
                result[output]["disk_num"] = disk_num
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_iostat_data", result])
        return result

    def process_vdbench_data(self, path, dirname):
        result = {}
        try:
            vdbench_data = {}
            runtime = int(self.common.bash("grep -o 'elapsed=[0-9]\+' "+path+" | cut -d = -f 2"))
            stdout, stderr = self.common.bash("grep 'avg_2-' "+path, True)
            vdbench_data = stdout.split()
            output_vdbench_data = OrderedDict()
            output_vdbench_data['read_lat'] = vdbench_data[8]
            output_vdbench_data["read_iops"] = vdbench_data[7]
            output_vdbench_data["read_bw"] = vdbench_data[11]
            output_vdbench_data['read_runtime'] = runtime
            output_vdbench_data['write_lat'] = vdbench_data[10]
            output_vdbench_data["write_iops"] = vdbench_data[9]
            output_vdbench_data["write_bw"] = vdbench_data[12]
            output_vdbench_data['write_runtime'] = runtime
            output_vdbench_data['lat_unit'] = 'msec'
            output_vdbench_data['runtime_unit'] = 'sec'
            output_vdbench_data['bw_unit'] = 'MB/s'
            output_vdbench_data['99.00th%_lat'] = '0'
            result[dirname] = {}
            result[dirname]["vdbench"] = output_vdbench_data
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_vdbench_data", result])
        return result

    def get_lat_persent_dict(self,fio_str):
        lat_percent_dict = {}
        tmp_list = fio_str.split(',')
        for i in tmp_list:
            li = i.split('=')
            while '' in li:li.remove('')
            if len(li) == 2 and li[1] != '':
                key = re.findall('.*?th',li[0].strip('\n').strip('| ').strip(' ').replace(' ',''),re.S)
                value = re.match(r'\[(.*?)\]',li[1].strip('\n').strip(' ').replace(' ','')).groups()
                if len(key) != 0 and len(value) != 0:
                    lat_percent_dict[key[0]] = value[0]
        return lat_percent_dict

    def process_fio_data(self, path, dirname):
        result = {}
        try:
            stdout = self.common.bash("grep \" *io=.*bw=.*iops=.*runt=.*\|^ *lat.*min=.*max=.*avg=.*stdev=.*\" "+path)
            stdout1 = self.common.bash("grep \" *1.00th.*],\| *30.00th.*],\| *70.00th.*],\| *99.00th.*],\| *99.99th.*]\" "+path)
            stdout2 = self.common.bash("grep \" *clat percentiles\" "+path)
    
            lat_per_dict = {}
            if stdout1 != '':
                lat_per_dict = self.get_lat_persent_dict(stdout1)
    
            fio_data_rw = {}
            fio_data_rw["read"] = {}
            fio_data_rw["write"] = {}
            for data in re.split(',|\n|:',stdout):
                try:
                    key, value = data.split('=')
                    if key.strip().lower() not in fio_data:
                        fio_data[key.strip().lower()] = []
                        fio_data[key.strip().lower()].append( value.strip() )
                except:
                    if 'lat' in data:
                        res = re.search('lat\s*\((\w+)\)',data)
                        if 'lat_unit' not in fio_data:
                            fio_data['lat_unit'] = []
                        fio_data['lat_unit'].append( res.group(1) )
                    if "read" in data:
                        fio_data = fio_data_rw["read"]
                    if "write" in data:
                        fio_data = fio_data_rw["write"]
    
            output_fio_data = OrderedDict()
            output_fio_data['read_lat'] = 0
            output_fio_data['read_iops'] = 0
            output_fio_data['read_bw'] = 0
            output_fio_data['read_runtime'] = 0
            output_fio_data['write_lat'] = 0
            output_fio_data['write_iops'] = 0
            output_fio_data['write_bw'] = 0
            output_fio_data['write_runtime'] = 0
    
            if len(lat_per_dict) != 0:
                for tmp_key in ["95.00th", "99.00th", "99.99th"]:
                    if tmp_key in lat_per_dict.keys():
                        lat_persent_unit = re.findall(r"(?<=[\(])[^\)]+(?=[\)])", stdout2.strip('\n').strip(' ').replace(' ',''))
                        if len(lat_persent_unit) != 0:
                            output_fio_data[tmp_key+"%_lat"] = float(self.common.time_to_sec("%s%s" % (lat_per_dict[tmp_key], lat_persent_unit[0]),'msec'))
                        else:
                            output_fio_data[tmp_key+"%_lat"] = 'null'
                    else:
                        output_fio_data[tmp_key+"%_lat"] = 'null'
            output_fio_data['lat_unit'] = 'msec'
            output_fio_data['runtime_unit'] = 'sec'
            output_fio_data['bw_unit'] = 'MB/s'
            for io_pattern in ['read', 'write']:
                if fio_data_rw[io_pattern] != {}:
                    first_item = fio_data_rw[io_pattern].keys()[0]
                else:
                    continue
                list_len = len(fio_data_rw[io_pattern][first_item])
                for index in range(0, list_len):
                    fio_data = fio_data_rw[io_pattern]
                    if "avg" in fio_data:
                        output_fio_data['%s_lat' % io_pattern] += float(self.common.time_to_sec("%s%s" % (fio_data['avg'][index], fio_data['lat_unit'][index]),'msec'))
                    if "iops" in fio_data:
                        output_fio_data['%s_iops' % io_pattern] += int(fio_data['iops'][index])
                    if "bw" in fio_data:
                        res = re.search('(\d+\.*\d*)\s*(\w+)/s',fio_data['bw'][index])
                        if res:
                            output_fio_data['%s_bw' % io_pattern] += float( self.common.size_to_Kbytes("%s%s" % (res.group(1), res.group(2)),'MB') )
                    if "runt" in fio_data:
                        output_fio_data['%s_runtime' % io_pattern] += float( self.common.time_to_sec(fio_data['runt'][index], 'sec') )
                output_fio_data['%s_lat' % io_pattern] /= list_len
                output_fio_data['%s_runtime' % io_pattern] /= list_len
            result[dirname] = {}
            result[dirname]["fio"] = output_fio_data
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data( ["process_fio_data", result] )
        return result

    def process_lttng_data(self, path):
        pass

    def process_perf_data(self, path):
        pass

    def process_blktrace_data(self, path):
        pass

    def process_perfcounter_data(self, dir_name, path):
        result = self.common.MergableDict()
        try:
            precise_level = int(self.cluster["perfcounter_time_precision_level"])
    #        precise_level = 6
            self.common.printout("LOG","loading %s" % path)
            perfcounter = []
            with open(path,"r") as fd:
                data = fd.readlines()
            for tmp_data in data:
                if ',' == tmp_data[-2]:
                    tmp_data = tmp_data[:-2]
                try:
                    perfcounter.append(json.loads(tmp_data, object_pairs_hook=OrderedDict))
                except:
                    perfcounter.append({})
            if not len(perfcounter) > 0:
                return False
            lastcounter = perfcounter[0]
            for counter in perfcounter[1:]:
                result.update(counter, dedup=False, diff=False)
            result = result.get()
            output = OrderedDict()
    #        for key in ["osd", "filestore", "objecter", "mutex-JOS::SubmitManager::lock"]:
            for key in self.cluster["perfcounter_data_type"]:
                result_key = key
                find = True
                if key != "librbd" and key not in result:
                    continue
                if key == "librbd":
                    find = False
                    for result_key in result.keys():
                        if key in result_key:
                            find = True
                            break
                if not find:
                    continue
                output["perfcounter_"+key] = {}
                current = output["perfcounter_"+key]
                for param, data in result[result_key].items():
                    if isinstance(data, list):
                        if not param in current:
                            current[param] = []
                        current[param].extend( data )
                    if isinstance(data, dict) and 'avgcount' in data and 'sum' in data:
                        if not isinstance(data['sum'], list):
                            continue
                        if not param in current:
                            current[param] = []
                        last_sum = data['sum'][0]
                        last_avgcount = data['avgcount'][0]
                        for i in range(1, len(data['sum'])):
                            try:
                                current[param].append( round((data['sum'][i]-last_sum)/(data['avgcount'][i]-last_avgcount),precise_level) )
                            except:
                                current[param].append(0)
                            last_sum = data['sum'][i]
                            last_avgcount = data['avgcount'][i]
        except:
            err_log = traceback.format_exc()
            self.common.printout("ERROR","%s" % err_log)
        self.workpool.enqueue_data(["process_perfcounter_data", dir_name, output])
        return output


class WorkPool:
    def __init__(self, cn):
        #1. get system available
        self.cpu_total = multiprocessing.cpu_count()
        self.running_process = []
        self.lock = Lock()
        self.process_return_val_queue = Queue()
        self.common = cn
        self.queue_check = False
        self.inflight_process_count = 0

    def schedule(self, function_name, *argv):
        self.wait_at_least_one_free_process()
        if (self.cpu_total - len(self.running_process)) > 0:
            p = Process(target=function_name, args=tuple(argv))
            p.daemon = True
            self.running_process.append(p)
            self.inflight_process_count += 1
            p.start()
            self.common.printout("LOG","Process "+str(p.pid)+", function_name:"+str(function_name.__name__))

            check_thread = threading.Thread(target=self.update_result, args = ())
            check_thread.daemon = True
            check_thread.start()

    def wait_at_least_one_free_process(self):
        start = time.clock()
        while (self.cpu_total - len(self.running_process)) <= 0:
            for proc in self.running_process:
                if not proc.is_alive():
                    proc.join()
                    self.running_process.remove(proc)
                    return
            if time.clock() - start > 1:
                self.common.printout("LOG","Looking for available process, %d proc pending, pids are: %s" % (len(self.running_process), [x.pid for x in self.running_process]))
                start = time.clock()

    def wait_all(self):
        running_proc = self.running_process
        self.common.printout("LOG","Waiting %d Processes to be done" % len(running_proc))
  
        for proc in running_proc:
            proc.join()
            self.running_process.remove(proc)
            self.common.printout("LOG","PID %d Joined" % proc.pid)
        while self.inflight_process_count:
            time.sleep(1)

    def set_return_data_set(self, fio_log_res, workload_result, result):
        self.fio_log_res = fio_log_res
        self.workload_result = workload_result
        self.result = result

    def update_result(self):
        if self.queue_check:
            return
        self.queue_check = True
        while self.inflight_process_count:
            if self.process_return_val_queue.empty():
                time.sleep(1)
                continue
            res = self.process_return_val_queue.get()
            self.inflight_process_count -= 1
            self.common.printout("LOG", "Updating on %s" % res[0])
            if res[0] == "process_smartinfo_data":
                self.result.update(res[1])
            elif res[0] == "process_cosbench_data":
                self.workload_result.update(res[1])
            elif res[0] == "process_sar_data":
                self.result.update(res[1])
            elif res[0] == "process_vdbench_data":
                self.workload_result.update(res[1])
            elif res[0] == "process_fio_data":
                self.workload_result.update(res[1])
            elif res[0] == "process_fiolog_data":
                volume = res[1]
                if volume not in self.fio_log_res:
                    self.fio_log_res[volume] = {}
                    self.fio_log_res[volume]["fio_log"] = {}
                self.fio_log_res[volume]["fio_log"].update(res[2])
                self.workload_result.update(self.fio_log_res)
            elif res[0] == "process_iostat_data":
                self.result.update(res[1])
            elif res[0] == "process_log_data":
                self.result.update(res[1])
            elif res[0] == "process_perfcounter_data":
                dir_name = res[1]
                for key, value in res[2].items():
                    if dir_name not in self.workload_result:
                        self.workload_result[dir_name] = OrderedDict()
                    self.workload_result[dir_name][key] = value
            self.common.printout("LOG","%d inflight_processes remain." % self.inflight_process_count)
        self.queue_check = False

    def enqueue_data(self, data):
        self.process_return_val_queue.put(data)

def main(args):
    parser = argparse.ArgumentParser(description='Analyzer tool')
    parser.add_argument(
        'operation',
        )
    parser.add_argument(
        '--path',
        )
    parser.add_argument(
        '--path_detail',
        )
    parser.add_argument(
        '--node',
        )
    parser.add_argument(
        '--name',
        )
    args = parser.parse_args(args)
    process = Analyzer(args.path,args.name)
    if args.operation == "process_data":
        process.process_data()
    else:
        func = getattr(process, args.operation)
        if func:
            func(args.path_detail)

if __name__ == '__main__':
    import sys
    main(sys.argv[1:])
