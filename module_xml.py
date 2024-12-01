# coding: windows-1252
#
# ModulName: module_xml
# Klassen:
# CondExpression:
# ObjectScript: N
# ContainerScript: N
# EventType:
# EventClass:
# EventMembers:
# ExtendedRights: N
# ModulDescription: Provides functions to read and create xml files.
#
# 2024-06-06, CBR: Erstellt.
# 2024-06-25, CBR: V101. Aufbereitet f�r Konzept.
# 2024-08-08, CBR: V102. Wg. Performance vtcapp.rendertemplate ausgebaut.
# 2024-08.22, CBR: V103. PEP Update
# 2024-11-05, CBR: V104. Defaultwerte angepasst, Nodes nur mit Attributen nicht mehr
#                           bereinigen.
# 2024-11-25, CBR: V105. In Parser, Lexer und Serializer aufgeteilt. 


import re
from collections import deque


RAISE_NONE_ERROR = False
XML_REPLACEMENT_CHARS = {
    '&quot;': '"',
    '&apos;': "'",
    '&lt;': '<',
    '&gt;': '>',
    '&amp;': '&',
}
# Python 2.7 and 3 compatible
try:
    BASESTRING = basestring  # type: ignore
except NameError:
    BASESTRING = str


class RegexCollector(object):
    """
    Provides the regexes to parse a xml string. RegEx taken from
    "REX: XML Shallow Parsing with Regular Expressions", Robert D. Cameron,
    Markup Languages: Theory and Applications, Summer 1999, pp. 61-88,
    """

    def __init__(self):
        self.res = {}

        # Add the used regex functions.
        self.add("GetAttr", "(\S*?)=\"(.*?)\"")
        self.add("TextSE" , "[^<]+")
        self.add("UntilHyphen" , "[^-]*-")
        self.add("Until2Hyphens" , "%(UntilHyphen)s(?:[^-]%(UntilHyphen)s)*-")
        self.add("CommentCE" , "%(Until2Hyphens)s>?")
        self.add("UntilRSBs" , "[^\\]]*](?:[^\\]]+])*]+")
        self.add("CDATA_CE" , "%(UntilRSBs)s(?:[^\\]>]%(UntilRSBs)s)*>" )
        self.add("S" , "[ \\n\\t\\r]+")
        self.add("NameStrt" , "[A-Za-z_:]|[^\\x00-\\x7F]")
        self.add("NameChar" , "[A-Za-z0-9_:.-]|[^\\x00-\\x7F]")
        self.add("Name" , "(?:%(NameStrt)s)(?:%(NameChar)s)*")
        self.add("QuoteSE" , "\"[^\"]*\"|'[^']*'")
        self.add("DT_IdentSE" , "%(S)s%(Name)s(?:%(S)s(?:%(Name)s|%(QuoteSE)s))*" )
        self.add("MarkupDeclCE" , "(?:[^\\]\"'><]+|%(QuoteSE)s)*>" )
        self.add("S1" , "[\\n\\r\\t ]")
        self.add("UntilQMs" , "[^?]*\\?+")
        self.add("PI_Tail" , "\\?>|%(S1)s%(UntilQMs)s(?:[^>?]%(UntilQMs)s)*>" )
        self.add("DT_ItemSE" ,
            "<(?:!(?:--%(Until2Hyphens)s>|[^-]%(MarkupDeclCE)s)|\\?%(Name)s"
            "(?:%(PI_Tail)s))|%%%(Name)s;|%(S)s"
        )
        self.add("DocTypeCE" ,
        "%(DT_IdentSE)s(?:%(S)s)?(?:\\[(?:%(DT_ItemSE)s)*](?:%(S)s)?)?>?" )
        self.add("DeclCE" ,
            "--(?:%(CommentCE)s)?|\\[CDATA\\[(?:%(CDATA_CE)s)?|DOCTYPE"
            "(?:%(DocTypeCE)s)?")
        self.add("PI_CE" , "%(Name)s(?:%(PI_Tail)s)?")
        self.add("EndTagCE" , "%(Name)s(?:%(S)s)?>?")
        self.add("AttValSE" , "\"[^<\"]*\"|'[^<']*'")
        self.add("ElemTagCE" ,
            "%(Name)s(?:%(S)s%(Name)s(?:%(S)s)?=(?:%(S)s)?(?:%(AttValSE)s))*"
            "(?:%(S)s)?/?>?")

        self.add("MarkupSPE" ,
            "<(?:!(?:%(DeclCE)s)?|\\?(?:%(PI_CE)s)?|/(?:%(EndTagCE)s)?|"
            "(?:%(ElemTagCE)s)?)")
        self.add("XML_SPE" , "%(TextSE)s|%(MarkupSPE)s")
        self.add("XML_MARKUP_ONLY_SPE" , "%(MarkupSPE)s")

    def add(self, name, reg):
        re.compile(reg)
        self.res[name] = reg % self.res


class XmlParser(object):
    """
    Converts a provided xml string to python objects.
    If a XmlRoot is provided, we updated it.
    If not, we return a new XmlRoot.
    """

    def __init__(self, xmlstring, xml_root=None):
        self.xml_string = xmlstring
        self.tokens_processed = deque([])

        # initialize collector and compile used regex
        self.collector = RegexCollector()
        self.full_regex = re.compile(self.collector.res["XML_SPE"])
        self.attr_regex = re.compile(self.collector.res["GetAttr"])
        self.tag_regex = re.compile(self.collector.res["Name"])

        # Create tokens
        self.tokens = self._findall(self.xml_string, self.full_regex)

        # Check tokens
        self._assert_lex()

        # Create XML-Root
        self.xml_root = (xml_root if xml_root else XmlRoot())
        self.current_node = None
        self.parent_nodes = deque([])

    def _findall(self, string, regex):
        """
        Finds all occurences using regex.
        """
        return regex.findall(string)

    def _get_attributes(self, string):
        """
        Extracts the attributes of the token into a dict.
        """
        attribute_list = self._findall(string, self.attr_regex)
        if attribute_list:
            return {attribute[0]: attribute[1] for attribute in attribute_list}
        
        return {}
    
    def _get_position(self):
        """
        Returns the position of the error using the processed string.
        First the column no. and then the line no..
        """
        processed_string = "".join(self.tokens_processed)
        lines = processed_string.splitlines()
        if not lines:
            return 0, 0
        
        return len(lines), len(lines[-1])

    def _get_tag(self, string):
        """
        Returns the tag value of the string.
        """
        tags = self._findall(string, self.tag_regex)
        if len(tags) == 0:
            column, line = self._get_position()
            raise XmlException("No tag name found for string {} (Column {}, Line {}).".format(string, column, line))
        else:
            return tags[0]

    def _assert_lex(self):
        """
        Checks if the lexing did not loose any data.
        """
        assert "".join(self.tokens) == self.xml_string

    def _process_procinstr(self, token):
        """
        Processing instructions.
        """
        print("PROCINSTR", token)

    def _process_xmldeclaration(self, token):
        """
        Processing instructions.
        """
        attributes = self._get_attributes(token)

        if 'version' in attributes.keys():
            self.xml_root.version = attributes['version']
        if 'encoding' in attributes.keys():
            self.xml_root.encoding = attributes['encoding']
        if 'standalone' in attributes.keys():
            self.xml_root.standalone = attributes['standalone']

    def _process_startnode(self, token):
        """
        Processes a single node. Either self closing or open.
        """
        # Create new node and make it current.
        node = XmlNode(self._get_tag(token))
        self.current_node = node
        node.attributes = self._get_attributes(token)

        # Add to node list. Either as rootnode or to another node.
        if len(self.parent_nodes) == 0:
            self.xml_root.rootnode = node
        else:
            self.parent_nodes[-1].nodes.append(node)
        self.parent_nodes.append(node)
    
    def _process_endnode(self, token):
        """
        Processes the endnode.
        """
        tag = self._get_tag(token)

        if not self.current_node:
            column, line = self._get_position()
            raise XmlException("Closing node {} found, but no open node (Column {}, Line {})".format(tag, column, line))

        if self.current_node.tag != tag:
            column, line = self._get_position()
            raise XmlException("Closing node tag ({}) and open node tag ({}) do not match (Column {}, Line {}).".format(tag, self.current_node.tag, column, line))

        self.parent_nodes.pop()
        self.current_node = (self.parent_nodes[-1] if self.parent_nodes else None)
    
    def parse_xml(self):
        """
        Parses the xml data and creates or
        updates the XmlRoot and XmlNodes.
        """

        for token in self.tokens:
            # Process value
            if token.startswith("<"):
                if token.startswith("<!--"):
                    pass # print("comment:", token)

                elif token.startswith("<![CDATA"):
                    pass # print("CDATA:", token)

                elif token.startswith("<!ELEMENT"):
                    pass # print("element:", token)

                elif token.startswith("<!ATTLIST"):
                    pass # print("attribute list:", token)

                elif token.startswith("<!ENTITY"):
                    pass # print("entitiy list:", token)

                elif token.startswith("<!DOCTYPE"):
                    pass # print("document type:", token)

                elif token.startswith("<!"):
                    pass # print("declaration:", token)

                elif token.startswith("<?xml"):
                    self._process_xmldeclaration(token)

                elif token.startswith("<?"):
                    self._process_procinstr(token)

                elif token.startswith("</"):
                    self._process_endnode(token)

                elif token.endswith("/>"):
                    self._process_startnode(token)
                    self._process_endnode(token)

                elif token.endswith(">"):
                    self._process_startnode(token)

                else:
                    print("error:", token)

            else:
                # If token.
                if self.current_node and token and not token.isspace():
                    self.current_node.value = token
            
            # Update processed lines
            self.tokens_processed.append(token)

        return self.xml_root


class XmlSerializer(object):
    """
    Converts a xml python python object to a xml string.
    """

    def __init__(self, xml_root):
        self.xml_root = xml_root
        self.xml_string = ""

    def serialize_xml(self):
        """
        Converts the XMLRoot object into an xml string.
        """
        attributes = {}
        if self.xml_root.version:
            attributes['version'] = self.xml_root.version
        if self.xml_root.encoding:
            attributes['encoding'] = self.xml_root.encoding
        if self.xml_root.standalone:
            attributes['standalone'] = self.xml_root.standalone

        if len(attributes) > 0:
            self.xml_string = '<?xml {} ?>\n'.format(self._attributes_to_xml(attributes))
        self.xml_string += "{}".format(self._to_xml(self.xml_root.rootnode, 0))

        return self.xml_string

    def _to_xml(self, node, intendation=0):
        """
        Internal function to convert all children nodes to an xml file.
        """

        intendationString = "".join(["\t" for i in range(intendation)])
        newlineString = ""

        # Filter empty nodes
        if node.is_empty():
            return ""

        # Either with or without attributes
        if node and node.attributes:
            xml = '{}<{} {}'.format(intendationString, node.tag,
                                     self._attributes_to_xml(node.attributes))
        else:
            xml = '{}<{}'.format(intendationString, node.tag)

        # Directly close node, if no nodes or value.
        if (not node.nodes or len(node.nodes) == 0 or node.nodes_are_empty()) and (not node.value):
            xml += "/>"
        
        # Either with nodes or with a value.
        else:
            xml += ">"

            # Add nodes.
            if node.nodes and len(node.nodes) > 0:
                for newNode in node.nodes:
                    xml += "\n"
                    xml += self._to_xml(newNode, intendation + 1)
                    newlineString = "\n"

                xml += '{}{}'.format(newlineString, intendationString)

            elif node.value:
                xml += self._encode_string(node.value)

            xml += '</{}>'.format(node.tag)

        return xml

    def _encode_string(self, value):
        """
        Escapes the value (<>&'"). First try with rendertemplate was slow.
        The replace Version is MUCH faster.
        """
        string = "{}".format(value)

        for escaped, original in XML_REPLACEMENT_CHARS.items():
            string = string.replace(original, escaped)

        return string

    def _attributes_to_xml(self, attributes):
        """
        Creates an attribute string from a dict.
        """

        output = ""

        if not attributes:
            return output

        if isinstance(attributes, dict):
            for key, value in attributes.items():
                if isinstance(value, BASESTRING):
                    # We always replace doublequots in string and wrap
                    # the values with doublequotes
                    value = value.replace(XML_REPLACEMENT_CHARS['&quot;'], '&quot;')

                output += '{}="{}" '.format(key, value)

        return output


class XmlRoot(object):
    """
    Representation of an xml file.
    XML files can only contain one root node.
    """

    def __init__(self, version=None, encoding="utf-8", standalone=None, rootnode=None):
        # Version should always be present -> force a value.
        self.version = (version if version else "1.0")

        # Other values are optional (except the roodnode,
        # but in most cases it is added later).
        self.encoding = encoding
        self.standalone = standalone
        self.rootnode = rootnode

    def __str__(self):
        return "XML Root"

    def __repr__(self):
        return "XML Root"

    def __name__(self):
        return "XMLRoot"

    def from_xml(self, xmlstring):
        """
        Converts an xml string into an XMLRoot object.
        """
        
        parser = XmlParser(xmlstring, self)

        # Parser returns the xml_root, which we do not need here.
        _ = parser.parse_xml()

    def to_xml(self):
        """
        Converts the XMLRoot object into an xml string.
        """

        parser = XmlSerializer(self)
        return parser.serialize_xml()


class XmlException(Exception):
    pass


class XmlNode(object):
    """
    Representation of a XML child node.
    Child nodes can either have a value or subnodes (nodes).
    Attributes are optional.
    """

    def __init__(self, tag, attributes=None, nodes=None, value=None):
        self.tag = tag
        self.attributes = (attributes if attributes else {})
        self.value = value
        self.nodes = (nodes if nodes else [])

    @property
    def namespaces(self):
        namespaces = {}
        for attribute, uri in self.attributes.items():
            if not attribute.startswith('xmlns'):
                continue
            # Namespace: always xmlns. If it includes : it has a prefix
            split_string = attribute.split(":")
            if len(split_string) == 1:
                prefix = 'vtc_global_ns'
            elif len(split_string) == 2:
                prefix = split_string[1]
            else:
                prefix = ":".join(split_string[1:])

            namespaces[prefix] = uri

        return namespaces

    @property
    def value(self):
        return self._name

    @value.setter
    def value(self, value):
        self._name = self._decode_string(value)

    def __str__(self):
        return self.tag

    def __repr__(self):
        repr = "Node {}".format(self.tag)

        if self.attributes:
            repr += ", Attributes {}".format(self.attributes)

        return repr

    def __name__(self):
        return "XMLNode"

    def _decode_string(self, value):
        """
        Some chars have a special meaning and must be encoded.
        To further process the file, we need to decode them.
        """

        if value and isinstance(value, BASESTRING):
            for escaped, original in XML_REPLACEMENT_CHARS.items():
                value = value.replace(escaped, original)

        return value

    def nodes_are_empty(self):
        """
        Checks if all nodes are empty as well.
        """

        # Check if every node is also empty.
        for subnode in self.nodes:
            # If it isn't -> node is not empty.
            if not subnode.is_empty():
                return False

        # Nothing was not empty -> is empty.
        return True

    def is_empty(self):
        """
        Returns true, if the node and all subnodes of the node are empty.
        -> No nodes, no attributes, no value.
        """

        # Not empty, if if has attributes or values.
        if (self.value) or ((self.attributes) and (len(self.attributes) > 0)):
            return False

        # Empty if it has no nodes as well.
        if ((not self.nodes) or (len(self.nodes) == 0)):
            return True

        # Check if every node is also empty.
        return self.nodes_are_empty()

        return False

    def get_all_nodes(self, tag):
        """
        Searches for the notes with given tag.
        """

        allNodes = [node for node in self.nodes if node.tag.lower() == tag.lower()]

        return allNodes

    def get_first_node(self, tag):
        """
        Searches for the notes with given tag.
        """

        if isinstance(tag, list) and len(tag) > 1:
            tmp_tag = tag.pop(0)
            subnode = self.get_first_node(tmp_tag)

            if not subnode and RAISE_NONE_ERROR:
                raise XmlException("Subnode ({}) for parentnode ({}) not found."
                                   .format(tmp_tag, self.tag))

            elif not subnode:
                return None

            return subnode.get_first_node(tag)

        if isinstance(tag, list) and len(tag) == 1:
            return self.get_first_node(tag[0])

        else:
            allNodes = self.get_all_nodes(tag)

            if len(allNodes) > 0:
                return allNodes[0]

        return None

    def get_index(self, tag):
        """
        Returns the index of a node.
        """

        # We cannot provides indices for lists.
        if isinstance(tag, list):
            return None

        node = self.get_first_node(tag)

        if not node:
            return None

        return self.nodes.index(node)

    def get_value(self, tag):
        """
        Returns the value of a node.
        """
        node = self.get_first_node(tag)

        if not node:
            return None

        return node.value

    def set_value(self, tag, value):
        """
        Sets the value of a node.
        """
        node = self.get_first_node(tag)

        if node:
            node.value = value

    def get_nodes(self, tag):
        """
        Returns the nodes of a node.
        """
        node = self.get_first_node(tag)

        if not node:
            return None

        return node.nodes

    def set_nodes(self, tag, nodes):
        """
        Sets the nodes of a node.
        """
        node = self.get_first_node(tag)

        if node:
            node.nodes = nodes

    def get_attributes(self, tag):
        """
        Returns the attributes of a node.
        """

        node = self.get_first_node(tag)

        if not node:
            return None

        return node.attributes

    def set_attributes(self, tag, attributes):
        """
        Sets the attributes of a node.
        """

        node = self.get_first_node(tag)

        if node:
            node.attributes = attributes

    def _insert_helper(self, tag, node, add):
        """
        Helper to insert data into the existing node list.
        """

        # If we get a list, we pop the last entry,
        # because we need that one for the index.
        if isinstance(tag, list):
            if len(tag) > 1:
                index_tag = tag.pop(-1)
                parentnode = self.get_first_node(tag)
            elif len(tag) == 1:
                index_tag = tag[0]
                parentnode = self
            elif len(tag) == 0:
                return None

        # Else we use the tagname and parentnode directly.
        else:
            index_tag = tag
            parentnode = self

        if not parentnode:
            return

        index = parentnode.get_index(index_tag)

        if index is not None:
            parentnode.nodes.insert(index + add, node)

    def insert_before(self, tag, node):
        """
        Inserts the new node before the old node.
        """

        self._insert_helper(tag, node, add=0)

    def insert_after(self, tag, node):
        """
        Inserts the new node after the old node.
        """

        self._insert_helper(tag, node, add=1)


# Test part

def testlexer():
    import datetime
    xml_demo_string = """<?xml version="1.1" encoding="utf-8"?>
<h:configset xmlns:h="http://www.w3.org/TR/html4/" name="MUMMY XML " author="Vertec AG">
  <references>
    <entryid-reference class="DUMMY" alias="BearbeiterStufe0" entryid="UserLevel4" />
  </references>
  <objects>
    <object class="C10-AktivitaetsTyp" alias="AktivitaetsTyp_Verkauf1">
          <member name="M10-EintragID">ActivityTypeSales</member>
          <member name="M11-Modifier">
            <reference-object alias="Projektbearbeiter_Administrator6" />
          </member>
    </object>  
    <object class="C20-Projektbearbeiter" alias="Projektbearbeiter_Administrator6">
      <member name="M20-EintragID">UserAdmin</member>
      <member name="M21-timer" >
        <object class="C21-LeistungTimer" alias="LeistungTimer0">
          <member name="M211-StartZeit">1899-12-30T00:00:00 </member>
          <member name="M212-bearbeiter">
             <reference-object alias="Projektbearbeiter_Administrator6" />
          </member>
        </object>
      </member>
    </object>
    <object class="C30-Aktivitaet" alias="Aktivitaet_27.06.2019,NachfassenAngebotfürNachbereitung6">
      <member name="M30-Datum">2019-06-27T00:00:00</member>
      <member name="M31-Titel">Nachfassen Angebot für Nachbereitung</member>
    </object>
  </objects>  
</h:configset>"""

    from cProfile import Profile
    from pstats import SortKey, Stats

    #file = open('/Users/christian/Documents/vxml/test_small.xml', 'r')
    #file = open('/Users/christian/Documents/vxml/test_mid.xml', 'r')
    #file = open('/Users/christian/Documents/vxml/test.xml', 'r')
    #file = open('/Users/christian/Documents/vxml/ConfigSet_Camt Import.xml', 'r')
    #content = file.read()
    content = xml_demo_string

    xml = XmlRoot()
    with Profile() as profile:
        print(f"{xml.from_xml(content) = }")
        (
            Stats(profile)
            .strip_dirs()
            .sort_stats(SortKey.CUMULATIVE)
            .print_stats()
        )

    print(xml.to_xml())

    print(xml.rootnode.namespaces)

testlexer()