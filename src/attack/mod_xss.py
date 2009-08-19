#!/usr/bin/env python
import random
import re
import socket
from net import BeautifulSoup
from attack import Attack
from vulnerability import Vulnerability
from vulnerabilitiesdescriptions import VulnerabilitiesDescriptions as VulDescrip

class mod_xss(Attack):
  """
  This class implements a cross site scripting attack
  """

  # magic strings we must see to be sure script is vulnerable to XSS
  # payloads must be created on those paterns
  script_ok = [
      "alert('__XSS__')",
      "alert(\"__XSS__\")",
      "String.fromCharCode(0,__XSS__,1)"
      ]

  # simple payloads that doesn't rely on their position in the DOM structure
  # payloads injected after closing a tag aatibute value (attrval) or in the
  # content of a tag (text node like beetween <p> and </p>)
  # only trick here must be on character encoding, filter bypassing, stuff like that
  # form the simplest to the most complex, Wapiti will stop on the first working
  independant_payloads = []
  
  name = "xss"

  xss_history = {} # will be removed later
  HTTP = None

  # two dict for permanent XSS scanning
  GET_XSS = {}
  POST_XSS = {}

  CONFIG_FILE = "xssPayloads.txt"

  def __init__(self, HTTP, xmlRepGenerator):
    Attack.__init__(self, HTTP, xmlRepGenerator)
    self.independant_payloads = self.loadPayloads(self.CONFIG_DIR+"/"+self.CONFIG_FILE)

  def attackGET(self, page, dict, attackedGET, headers = {}):
    """This method performs the cross site scripting attack (XSS attack) with method GET"""
    # page est l'url de script
    # dict est l'ensembre des variables et leurs valeurs
    if dict == {}:
      url = page+"?__XSS__"
      if url not in attackedGET:
        attackedGET.append(url)
        err = ""
        code = "".join([random.choice("0123456789abcdefghjijklmnopqrstuvwxyz") for i in range(0,10)]) # don't use upercase as BS make some data lowercase
        url = page+"?"+code
        self.GET_XSS[code] = url
        try:
          data = self.HTTP.send(url).getPage()
        except socket.timeout:
          data = ""
        if data.find(code) >= 0:
          self.findXSS(data, page, {}, "", code)

    else:
      for k in dict.keys():
        err = ""
        tmp = dict.copy()
        tmp[k] = "__XSS__"
        url = page+"?"+self.HTTP.uqe(tmp)
        if url not in attackedGET:
          attackedGET.append(url)
          # genere un identifiant unique a rechercher ensuite dans la page
          code = "".join([random.choice("0123456789abcdefghjijklmnopqrstuvwxyz") for i in range(0,10)]) # don't use upercase as BS make some data lowercase
          tmp[k] = code
          url = page+"?"+self.HTTP.uqe(tmp)
          self.GET_XSS[code] = url
          try:
            data = self.HTTP.send(url).getPage()
          except socket.timeout:
            data = ""
          # on effectue une recherche rapide sur l'indetifiant
          if data.find(code) >= 0:
            # identifiant est dans la page, il faut determiner ou
            if self.findXSS(data, page, tmp, k, code):
              break

  def attackPOST(self, form, attackedPOST):
    """This method performs the cross site scripting attack (XSS attack) with method POST"""
    headers = {"Accept": "text/plain"}
    page = form[0]
    params = form[1]
    for k in params.keys():
      tmp = params
      log = params.copy()

      log[k] = "__XSS__"
      if (page,log) not in attackedPOST:
        attackedPOST.append((page, log))
        code = "".join([random.choice("0123456789abcdefghjijklmnopqrstuvwxyz") for i in range(0,10)]) # don't use upercase as BS make some data lowercase
        tmp[k] = code
        # will only memorize the last used payload (working or not) but the code will always be the good
        self.POST_XSS[code] = [page, tmp, form[2]]
        try:
          data = self.HTTP.send(page, self.HTTP.uqe(tmp), headers).getPage()
        except socket.timeout:
          data = ""
        # rapid search on the code to check injection
        if data.find(code) >= 0:
          # found, now study where and what is possible
          if self.findXSS(data, page, tmp, k, code, form[2]):
            break


  def permanentXSS(self,url):
    """This method searches XSS which could be permanently stored in the web application"""
    headers = {"Accept": "text/plain"}
    if self.verbose >= 1:
      print "+", url
    try:
      data = self.HTTP.send(url).getPage()
    except socket.timeout:
      data = ""
    for code in self.GET_XSS.keys():
      if data.find(code) >= 0:
        # we where able to inject the ID but will we be able to inject javascript?
        for xss in self.independant_payloads:
          attack_url = self.GET_XSS[code].replace(code, xss.replace("__XSS__", code))
          try:
            self.HTTP.send(attack_url)
            dat = self.HTTP.send(url).getPage()
          except socket.timeout:
            dat = ""
          if self.validXSS(dat, code):
            print _("Found permanent XSS in"), url, _("with"),attack_url
            self.reportGen.logVulnerability(Vulnerability.XSS,
                            Vulnerability.HIGH_LEVEL_VULNERABILITY, url, "",
                            _("Found permanent XSS in")+" "+url+" "+_("with")+" "+attack_url)
            break

    for code in self.POST_XSS.keys():
      if data.find(code) >= 0:
        for k, v in self.POST_XSS[code][1].items():
          if v == code:
            tmp = self.POST_XSS[code][1].copy()
            for xss in self.independant_payloads:
              tmp[k] = xss.replace("__XSS__", code)
              try:
                self.HTTP.send(self.POST_XSS[code][0], self.HTTP.uqe(tmp), headers)
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""
              if self.validXSS(dat,code):
                self.reportGen.logVulnerability(Vulnerability.XSS,
                            Vulnerability.HIGH_LEVEL_VULNERABILITY, url,"",
                            _("Found permanent XSS attacked by")+" "+self.POST_XSS[code][0]+
                            " "+_("with field")+" "+self.HTTP.uqe(self.POST_XSS[code][1]))
                print _("Found permanent XSS in"), self.POST_XSS[code][0]
                print "  "+_("attacked by"), self.POST_XSS[code][2], _("with fields"), self.HTTP.uqe(tmp)
                break

  # type/name/tag ex: attrval/img/src
  def study(self, obj, parent=None, keyword="", entries=[]):
    #if parent==None:
    #  print "Keyword is:",keyword
    if str(obj).find(keyword) >= 0:
      if isinstance(obj, BeautifulSoup.Tag):
        if str(obj.attrs).find(keyword) >= 0:
          for k, v in obj.attrs:
            if v.find(keyword) >= 0:
              #print "Found in attribute value ",k,"of tag",obj.name
              entries.append({"type":"attrval", "name":k, "tag":obj.name})
            if k.find(keyword) >= 0:
              #print "Found in attribute name ",k,"of tag",obj.name
              entries.append({"type":"attrname", "name":k, "tag":obj.name})
        elif obj.name.find(keyword) >= 0:
          #print "Found in tag name"
          entries.append({"type":"tag", "value":obj.name})
        else:
          for x in obj.contents:
            self.study(x, obj, keyword,entries)
      elif isinstance(obj, BeautifulSoup.NavigableString):
        if str(obj).find(keyword) >= 0:
          #print "Found in text, tag", parent.name
          entries.append({"type":"text", "parent":parent.name})

  def validXSS(self,page,code):
    soup=BeautifulSoup.BeautifulSoup(page)
    for x in soup.findAll("script"):
      #if x.string != None: print "-"+x.string+"-"
      if x.string != None and x.string in [t.replace("__XSS__", code) for t in self.script_ok]:
        return True
      elif x.has_key("src"):
        if x["src"] == "http://__XSS__/x.js".replace("__XSS__", code):
          return True
    return False



  # GET and POST methods here
  def findXSS(self, data, page, args, var, code, referer = ""):
    headers = {"Accept": "text/plain"}
    params = args.copy()
    soup = BeautifulSoup.BeautifulSoup(data) # il faut garder la page non-retouchee en reserve...
    e = []
    self.study(soup, keyword = code, entries = e)
    url = page
    for elem in e:
      payload = ""
      # traiter chaque entree au cas par cas
      # on quitte a la premiere entree exploitable

      # common situation
      if elem['type'] == "attrval":
        #print "tag->"+elem['tag']
        #print elem['name']
        i0 = data.find(code)
        #i1=data[:i0].rfind("=")
        try:
          i1 = data[:i0].rfind(elem['name'])
        # stupid unicode errors, must check later
        except UnicodeDecodeError:
          continue

        start = data[i1:i0].replace(" ", "")[len(elem['name']):]
        if start.startswith("='"): payload="'"
        if start.startswith('="'): payload='"'
        if elem['tag'].lower() == "img":
          payload += "/>"
        else:
          payload += "></"+elem['tag']+">"

        # ok let's send the requests
        for xss in self.independant_payloads:
          if params == {}:
            url = page+"?"+payload+xss.replace("__XSS__", code)
            try:
              dat = self.HTTP.send(url).getPage()
            except socket.timeout:
              dat = ""
            var = "QUERY_STRING"
          else:
            params[var] = payload+xss.replace("__XSS__", code)
            if referer != "": #POST
              if self.verbose == 2:
                print "+ "+ page
                print "  ", params
              try:
                dat = self.HTTP.send(page, self.HTTP.uqe(params), headers).getPage()
              except socket.timeout:
                dat = ""
            else:#GET
              url = page+"?"+self.HTTP.uqe(params)
              try:
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""

          if self.validXSS(dat, code):
            if params != {}:
              self.reportGen.logVulnerability(Vulnerability.XSS,
                                Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                url, self.HTTP.uqe(params),
                                _("XSS")+" ("+var+")")
            else:
              self.reportGen.logVulnerability(Vulnerability.XSS,
                                Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                url, url.split("?")[1],
                                _("XSS")+" ("+var+")")

            if referer != "":
              print _("Found XSS in"), page
              print "  "+_("with params")+" =", self.HTTP.encode(params)
              print "  "+_("coming from"), referer

            else:
              if self.color == 0:
                print _("XSS")+" ("+var+") "+_("in"), page
                print "\t"+_("Evil url")+":", url
              else:
                print _("XSS"), ":", url.replace(var+"=", "\033[0;31m"+var+"\033[0;0m=")
            return True

      # this should not happen but you never know...
      elif elem['type'] == "attrname": # name,tag
        #print "attrname"
        if code == elem['name']:
          for xss in self.independant_payloads:
            if params == {}:
              url = page+"?"+xss.replace("__XSS__",code)
              try:
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""
              var = "QUERY_STRING"
            else:
              params[var] = '>'+xss.replace("__XSS__",code)

              if referer != "": #POST
                if self.verbose == 2:
                  print "+ "+page
                  print "  ", params
                try:
                  dat = self.HTTP.send(page, self.HTTP.uqe(params), headers).getPage()
                except socket.timeout:
                  dat = ""
              else:
                url = page+"?"+self.HTTP.uqe(params)
                try:
                  dat = self.HTTP.send(url).getPage()
                except socket.timeout:
                  dat=""

            if self.validXSS(dat, code):
              if params != {}:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, self.HTTP.uqe(params),
                                  _("XSS")+"  ("+var+")")
              else:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, url.split("?")[1],
                                  _("XSS")+"  ("+var+")")

              if referer != "":
                print _("Found XSS in"), page
                print "  "+_("with params")+" =", self.HTTP.encode(params)
                print "  "+_("coming from"), referer

              else:
                if self.color == 0:
                  print _("XSS")+" ("+var+") "+_("in"), page
                  print "\t"+_("Evil url")+":", url
                else:
                  print _("XSS"), ":", url.replace(var+"=", "\033[0;31m"+var+"\033[0;0m=")
              return True

      elif elem['type'] == "tag":
        if elem['value'].startswith(code):
          # use independant payloads, just remove the first character (<)
          for xss in self.independant_payloads:

            if params == {}:
              url = page+"?"+xss.replace("__XSS__", code)
              try:
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""
              var = "QUERY_STRING"

            else:
              params[var] = xss.replace("__XSS__", code)[1:]

              if referer != "": #POST
                if self.verbose == 2:
                  print "+ "+page
                  print "  ", params
                try:
                  dat = self.HTTP.send(page, self.HTTP.uqe(params), headers).getPage()
                except socket.timeout:
                  dat = ""
              else:
                url = page+"?"+self.HTTP.uqe(params)
                try:
                  dat = self.HTTP.send(url).getPage()
                except socket.timeout:
                  dat = ""

            if self.validXSS(dat, code):
              if params != {}:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, self.HTTP.uqe(params),
                                  _("XSS")+" ("+var+")")
              else:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, url.split("?")[1],
                                  _("XSS")+" ("+var+")")
              if referer != "":
                print _("Found XSS in"), page
                print "  "+_("with params")+" =", self.HTTP.encode(params)
                print "  "+_("coming from"), referer

              else:
                if self.color == 0:
                  print _("XSS")+" ("+var+") "+_("in"), page
                  print "\t"+_("Evil url")+":", url
                else:
                  print _("XSS"), ":", url.replace(var+"=", "\033[0;31m"+var+"\033[0;0m=")
              return True

        else:
          for xss in self.independant_payloads:

            if params == {}:
              url = page+"?"+xss.replace("__XSS__", code)
              try:
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""
              var = "QUERY_STRING"

            else:
              #close tag and inject independant payloads
              params[var] = "/>"+xss.replace("__XSS__", code)

              if referer != "": #POST
                if self.verbose == 2:
                  print "+ "+page
                  print "  ", params
                try:
                  dat = self.HTTP.send(page, self.HTTP.uqe(params), headers).getPage()
                except socket.timeout:
                  dat = ""
              else:
                url = page+"?"+self.HTTP.uqe(params)
                try:
                  dat = self.HTTP.send(url).getPage()
                except socket.timeout:
                  dat = ""

            if self.validXSS(dat, code):
              if params != {}:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, self.HTTP.uqe(params),
                                  _("XSS")+" ("+var+")")
              else:
                self.reportGen.logVulnerability(Vulnerability.XSS,
                                  Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                  url, url.split("?")[1],
                                  _("XSS")+" ("+var+")")
              if referer != "":
                print _("Found XSS in"), page
                print "  "+_("with params")+" =", self.HTTP.encode(params)
                print "  "+_("coming from"), referer

              else:
                if self.color == 0:
                  print _("XSS")+" ("+var+") in", page
                  print "\t"+_("Evil url")+":", url
                else:
                  print _("XSS"), ":", url.replace(var+"=", "\033[0;31m"+var+"\033[0;0m=")
              return True

      # another common one
      elif elem['type'] == "text":
        payload = ""
        if elem['parent'] == "title": # Oops we are in the head
          payload = "</title>"

        for xss in self.independant_payloads:
          if params == {}:
            url = page+"?"+payload+xss.replace("__XSS__", code)
            try:
              dat = self.HTTP.send(url).getPage()
            except socket.timeout:
              dat = ""
            var = "QUERY_STRING"
          else:
            params[var] = payload+xss.replace("__XSS__", code)

            if referer != "": #POST
              if self.verbose == 2:
                print "+ "+page
                print "  ", params
              try:
                dat = self.HTTP.send(page, self.HTTP.uqe(params), headers).getPage()
              except socket.timeout:
                dat = ""
            else:
              url = page+"?"+self.HTTP.uqe(params)
              try:
                dat = self.HTTP.send(url).getPage()
              except socket.timeout:
                dat = ""

          if self.validXSS(dat, code):
            if params != {}:
              self.reportGen.logVulnerability(Vulnerability.XSS,
                                Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                page, self.HTTP.uqe(params),
                                _("XSS")+" ("+var+")")
            else:
              self.reportGen.logVulnerability(Vulnerability.XSS,
                                Vulnerability.HIGH_LEVEL_VULNERABILITY,
                                self.HTTP.escape(url), url.split("?")[1],
                                _("XSS")+" ("+var+")")

            if referer != "":
              print _("Found XSS in"), page
              print "  "+_("with params")+" =", self.HTTP.encode(params)
              print "  "+_("coming from"), referer

            else:
              if self.color == 0:
                print _("XSS")+" ("+var+") in", page
                print "\t"+_("Evil url")+":", url
              else:
                print _("XSS"), ":", url.replace(var+"=", "\033[0;31m"+var+"\033[0;0m=")
            return True

      data = data.replace(code, "none", 1)#reduire la zone de recherche
    return False

